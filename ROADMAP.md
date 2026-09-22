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

**Amended 2026-09-16 — the hub (§3.18; §6 item 24); ADOPTED 2026-09-21 (item 24 (g), the user).** The three planes are the platform's infrastructure. Its
purpose, in the user's own definition, is two-sided: every reason to come to the platform stays — ask, run your own
SQL, read the Briefing, open an object, approve a change — and the platform also **receives** data, documents,
definitions and what people say where they already work, and **exports** findings, analyses, Briefings and proposals
to the groups that watch the things they are about, each with its receipt. What leaves is information the platform
has measured, never the data. The airport is the analogy — the map, the tower, customs, the schedule — and the
nomenclature does not change.

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
and ON-6 is RETIRED (§6 item 15, decided 2026-09-11). ON-3's first slice shipped the same day: one
object opened live by type and key, its links followed in place, the metrics, findings, notes and
declared actions around it measured rather than inferred, and a key in an answer's table opens it.
ON-4's first slice followed: a declared action takes an object, and an edit a human accepts on it is
merged into the next read with who accepted it. **ON-3b/ON-3c/ON-1b/ON-5 followed on 2026-09-11/12**
(the Fabric IQ amendments: the entity-type map, the agent reading the type, bindings, and timeseries
properties read as each object's latest value), **and the arc's leftovers closed 2026-09-12** — the
person declares through the web what only the API took, one accepted edit can be withdrawn, an object
reads by its name wherever a key was printed, and a frame over the readings (trailing, cumulative,
the reading before) reaches the object door as a per-object value the compiler measures like any
other. Arc MT was dropped the same day (§6 item 17): identity buys nothing where this actually runs.
**The SECOND MOVEMENT, measured and adopted 2026-09-12 (§3.15):** entity = table is still true by
construction (Lux 14 tables, 14 entities); no door creates an entity or a link; the scope is one
`(connection, schema)`; there is no process, promise or stage; and the investigation never consults
the ontology FIRST — it was bolted onto prompts that predate it, and only the text route was ever
measured. LuxExperience has ZERO dispatch lag (synthetic); Olist on `baef6c3e/ecommerce` holds the
real process (9.35% late dispatch, 8.11% late delivery, measured through the API). The user adopted
waves ON-7 (declared entity, parts, links — MERGED #494), ON-7b (explorer agents map the business
first — first slice built and its receipt taken 2026-09-13: one model call drafted Lux's 14 tables as 8
entities, every claim measured before it landed, and the falsifier fired once — tickets read under
Order — so the explorer stays on demand), ON-8 (one ontology, many sources — first slice built 2026-09-14: an
organisation's ontology keyed `org/domain` whose types and bindings live on any connection, a link across two read by key
through the batched-foreach engine, and every cross-source answer equal to the single statement), ON-9 (processes and
promises — first slice built and its receipt met 2026-09-13: Olist's order-to-delivery declared and counted
THROUGH the object door's compiler, 9.35% of lines broke the dispatch promise and 8.11% of orders the delivery
one, every number equal to its hand-written reference, and the late segment, the breach rate and the lag each
promise derives compile by construction), ON-10 (the investigation starts from the ontology — first slice built
2026-09-13: a question's business terms are resolved against the DECLARED ontology, with no model, before the deep
analysis's intake reads them, each definition compiled by the object door and the frame shown with the answer; through
the running API 15 of 18 Olist questions reached a declared definition and none of the 3 controls did; and the
falsifier HELD on its run the same day: on the 12 questions whose definition is declared and not in the schema, framed
answered 8 and raw 3, losing none raw answered and keeping all 3 controls — and HELD AGAIN on LuxExperience, where
seven rules and a refund process were declared live for it and the matcher met questions it was never developed on:
framed 9 of 13, raw 1, one loss, all 3 controls kept — so the framing stays; the matcher gaps that run found were then
fixed and measured with no model on a new set of 54 questions, 51 of 51 in scope) and fixed ON-7
first; §6 item 18 holds its two remaining shape questions (the first, ON-8's scope key, was taken as recommended).

**The hub, measured 2026-09-15 (§3.18).** Receives: seven warehouse kinds, uploads, Sheets, PDFs and scans, Confluence
and Notion definitions through KI's review lane, a Slack @mention, one inbound hook per automation, an allowlisted MCP
server's tools. Exports: Slack, webhook, Jira, the MCP server, proposals. **No email either way.** Five triggers and
twelve effects, and neither a promise nor a finding is a trigger; nothing links a thread, a ticket or an email to an
object; nothing routes — a `BriefSubscription` has no subject and no reader, and the Briefing's lead is ranked by one
profile's north stars for a reader that is always the company; `Principal` is a user and an org and there are **no
groups**; the grant store holds one privilege on one securable kind; `owner` is free text; row policies ship empty; a
metric's quality tests run only when someone clicks, so a failing tie-out never holds a number out of the Briefing.

---

## 2 · Shipped

**Arc CI · conversational intelligence** — platform tool roster (#335), AI SDK UIMessage/parts
in `web/`, chat-first home, tiered write-scope (personal artifacts direct, org-shared semantic
state proposal-only).

**SQL editor (SE-0…SE-8)** — the human plane, peer to the agent's. SE-6/SE-7
(2026-09-10) made it a working editor's editor: live templates, ⌥⏎ intentions,
multi-caret, find/replace, extractors, the grid as a data editor. SE-8 (2026-09-14)
closed the reference-console gap measured against the Databricks SQL editor docs:
the Run split-button carries the row limit and a run-all preference (⌘⇧↵ stays
single-statement); the output pane grew a ‹Results N of M› statement pager,
visualization TABS (each owning its config, with rename/duplicate/remove) and a
header tool cluster with ⤢ maximize; parameters became gear-configured widgets
(text/number/date/dropdown/multi-select, choices typed or from a saved query,
⚡ dynamic dates) that bind through `expand_list_params` (`IN :name` from a list,
expanded to scalar binds pre-translate at every connector seam) and save with the
query as `param_defs`; Schedule creates the monitor in place (`any_change` only —
thresholds stay un-invented); a ✨ assistant pane proposes SQL as Apply/Reject
diffs through `POST /query/assist` (coder role, run-gated buffer, never executes);
plus open-existing search, formatter preferences, OR result-filters, Esc-H,
⌥± font size, and CSV-for-Excel (the BOM is the feature).

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

### 3.7 · Arc DS — the Design arc (adopted 2026-08-31; decision §6.5; **the four phases COMPLETE 2026-09-02**; **SECOND MOVEMENT — the authored step — drafted AND ADOPTED 2026-09-19 at the user's direction, §6 item 26, all five clauses decided the same day; **ALL THREE BUILT the same day** — DS-17b, DS-19 and DS-18, with the live receipt on `baef6c3e`; the header read "nothing built" for a further day, which is §5's own prose-rot lesson a third time, and is corrected here rather than left to be re-discovered**)

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


#### The second movement — the authored step (drafted AND ADOPTED 2026-09-19 at the user's direction; §6 item 26, all five clauses decided the same day; DS-17b, then DS-19, then DS-18)

> **Origin.** The user, 2026-09-19, reading the Automations palette on the LuxExperience 9am chain:
> *"Surprisingly, we dont have code component in the Add Action component list.. this could be handy when
> User know required SQL and needs its synthesis to be delivered either in Inbox or slack or practically
> anywhere.. code should be python or SQL in my opinion.."* — and, once the measurement below was put to
> them: *"Add the rows-to-synthesis step to the roadmap.. but instead the component should say synthesize
> data output from previous node and context can be added in the current node… Plus, I do see Trusted Query
> as an item there but it needs to be generally available for explicity SQL input by the user.. think it
> through, I thinik it makes super sense.."*

**What is true today (measured 2026-09-19 on main `9b6b5fc1`, read-only — no model calls, no writes).**

- **A SQL step ships and the user could not see it.** `trusted_query` is `palette.py:124` at weight 90 — it
  sorts immediately after "Governed metric", which is the last row above the fold on a 1280-tall window.
  It renders its prereq sentence rather than a `+` because `list_trusted(conn_id)` counts **0** on every
  connection but one: all 11 trusted queries on this deployment sit on `workspace`, none on LuxExperience.
  So the palette was telling the truth and the truth was one scroll down, dimmed. 🔑 **A gated row below the
  fold reads as an absent capability** — the prereq grammar (`palette.py:244`) is right and its PLACEMENT is
  what failed; a kind that is dimmed on this connection ranks as if it were available.
- **The step names a query id, never SQL.** `REQUIRED_CONFIG["trusted_query"] = ("query_id",)`
  (`models.py:155`), and `models.py:148` carries the reasoning: *"there is no expression here for anyone to
  author, so there is none for anyone to inject."*
- **Python is refused by a named law**, `_NO_CODE_LAW` (`import_flow.py:36`): *"a node is a reference to a
  governed capability, never an implementation."* Sixteen component classes are refused by name at the flow
  import border, their conditional router among them because it takes a Python predicate string.
- **There is no path from rows to a write-up.** `trusted_query` publishes `("rows", "columns", "count")`
  (`dataflow.py:706`); `investigate` binds exactly one field, `question` (`dataflow.py:746`); and a binding
  REPLACES a field — this plane has no interpolation and refuses an expression language by the same
  reasoning as the code law (`dataflow.py:58`). So a chain can post raw rows, or ask a question in English
  and let the agent write the SQL, and **cannot say "here is my SQL, write it up."**

**The distinction this movement turns on, and why it is not a softening of the law.** Three threats were
collapsed into one sentence, and only two of them are the law's:

1. **An imported artefact carries executable behaviour** — someone else's flow JSON with a Python function
   in it. Refused at the border, unchanged, forever.
2. **A model authors an expression that then runs unattended** — the injection case. Refused, unchanged,
   and hardened by this movement rather than relaxed: the SQL field below is **human-authorable only**, and
   the propose path is guarded so a drafted step may carry every other field and never that one.
3. **A person types SQL they already own.** This is neither of the above, **and the product already permits
   it**: `routers/query.py` is a query runner where a human runs arbitrary SQL against these same
   connections, with a signed provenance receipt (`query.py:150`). Refusing the same act in the automations
   plane is not the law — it is an inconsistency the law was being asked to justify.

What an unattended run actually needs that an editor session does not is three things: it must really have
run before it is armed, a name must be against the content, and an edit must re-open both. That is not a new
gate to invent — **it is exactly the trusted-query lifecycle** (`routers/learning.py:240`: an edit resets to
`proposed`, or `draft` on failure, and clears the prior stamp, because *"an approval covers the content it
approved, nothing later"*).

- **DS-18 · Synthesize — write up what the step before produced — ✅ BUILT 2026-09-19.** A new effect kind, `synthesize`, whose
  input port is the FIRST in this plane to accept any published key rather than a named string: `rows` from
  a trusted query, `value` from a governed metric, `text` from an MCP call, `answer` or `summary` from an
  investigation, an outcome from a declared action. Beside it on the node, authored not bound, a `context`
  field — what to make of this data, in the author's own words (bindable too, so a trigger's payload can
  reach it). It publishes `answer`, and the cap it applied, stated rather than implied.
  **What makes it this platform's step and not a "call an LLM" node** — the honesty machinery that already
  exists, pointed at it: every number in the answer appears in the input it was handed (the numeric-grounding
  check, `e08b1116`'s lesson — a figure is salient however it is spelled); empty input yields a STATED
  refusal and never a paragraph about nothing (§3.11's `or {}` lesson: failed and healthy-empty must not
  render alike); the row cap is named in the output the way `mcp_call` publishes `truncated`, because a step
  reading the answer must be able to tell a whole one from half; and the answer carries the provenance of
  what it read, so a Slack message's receipt names the approved query behind it. One governed answer path,
  capped, spanned, audited, no model id in `aughor/`.
  **Falsifier:** a `synthesize` answer that states a number absent from its input. If that can happen, the
  step is wrong and ships behind nothing. ✅ **Held**: an answer inventing a plausible sum (2,315 from 1,412
  and 903) is refused twice and the step FAILS publishing nothing — the answer is discarded rather than
  caveated, because this value is bound into someone else's prose and nothing downstream would carry a
  warning.
  🔴 **A defect in the guard itself, found by reusing it.** `check_grounding` has been accusing correctly
  quoted figures of being fabricated whenever they fall at the END of a sentence: `_NUM_RE` ends in `\.?\d*`,
  so "903." is captured with its full stop and does not match an evidence set holding "903". "APAC did 903
  orders." passed and "APAC did 903." did not. It fires on where a number SITS rather than on whether it is
  true, and the guard's own docstring records that a false violation costs a real retry — so this was
  spending repairs, and failing honest reports, across the whole report pipeline. Fixed at the one place
  three call sites now share.
  🔑 **And a test that named the right property and could not fail on it**, caught by the mutation run: the
  zero-is-a-finding case passed a dict `{"count": 0}`, which is truthy whatever it contains, so a
  truthiness check survived. It asserts on the SCALAR a `metric_value.value` binding delivers now. Second
  instance of this shape in one session — see DS-17b's falsifier.
  **Receipt:** 18 tests + 1 regression on the grounding guard; six mutants killed (no-grounding-check ·
  publish-anyway-after-repair · empty-reaches-the-model · zero-counts-as-empty · cap-not-published ·
  trailing-dot-unfixed).
  ✅ **LIVE RECEIPT TAKEN 2026-09-19**, on Olist's DuckDB (`baef6c3e`, `main.superstore`, 9,994 rows), one
  chain, real model: `trusted_query` executed 4 rows and `synthesize` wrote *"Standard Class carries the most
  orders with 5968. This is more than the 1945 orders for Second Class, 1538 orders for First Class, and 543
  orders for Same Day."* — every one of the four figures is a value in the rows, `source: rollup.rows`,
  `truncated: false`.
  🔴 **And the live run is what found the last defect, which no test could have.** The first attempt failed with
  *"LLMProvider.complete() missing 1 required positional argument: 'response_model'"* — every call on that seam
  is STRUCTURED, and this module was passing plain text. It passed 18 tests because the test double accepted
  `**kw`: **a stub more permissive than the thing it stands for tests the stub.** Fixed with a typed `Summary`
  model, and the double now mirrors the real signature with a test asserting the two match and that
  `response_model` is required on both — mutating it back to `**kw` fails.
- **DS-19 · SQL a person authored — private to the chain, promotable later — ✅ BUILT 2026-09-19.** The Trusted query step gains a
  "write SQL" authoring mode: question + SQL typed on the node. On SAVE — not at 09:00 — it runs through
  `trusted_verify` exactly as the door does; verification is not optional and an edit resets the stamp, which
  is item 26 (b) as decided.
  **Scope, per item 26 (c) — the user's call, against the recommendation, and the better one:** a query
  authored on a node belongs to that chain and does NOT enter the connection's catalogue. A catalogue filled
  with one-off chain SQL stops being a catalogue, which is the thing it exists to be. A "Promote" door on the
  node moves it into the catalogue when it turns out to be worth reusing.
  🔑 **What keeps that from becoming a second governance store** — and this is the trap this repo has paid for
  before (two places holding one fact are two places that will disagree): a private query is still a row in
  the ONE trusted-query store, carrying its own verification, stamp and audit, marked as owned by its
  automation and hidden from the catalogue picker. **Promotion is a flag flip, not a data move**, and there
  is exactly one lifecycle to reason about. A verification record stored on the step itself is the shape to
  refuse.
  **The cost was predicted and did not arrive, which is worth recording as a correction.** The plan said the
  wire format would change — `REQUIRED_CONFIG` becoming *exactly one of* `query_id` or inline `question` +
  `sql`, with every validator needing the second shape. What shipped is narrower: the authored pair is
  accepted at the BOUNDARY and `materialise_authored_sql` mints the governed row on save, so a STORED step
  still carries a `query_id` and nothing else. The validator gained one conditional branch (the `notify` +
  `route_about` precedent, one kind over); `LIST_PUBLISHED`, the dataflow tables and every other validator
  were untouched. **A saved node is still a reference to a governed object** — the law's literal shape,
  kept, rather than traded for the capability.
  **Found while building, and it is the DS-17b lesson one layer down:** the dispatcher reads `list_trusted`,
  which now hides chain-owned rows — so without scoping, a chain could not run the query it had just
  authored. It opens exactly one extra door: the catalogue, plus THIS automation's own. Another chain's
  private SQL is not merely refused, it is not there.
  **And the palette follows the module's own rule rather than an exception to it:** a kind whose required key
  is a value a person types "has nothing to be missing and is always ready", so `trusted_query` loses its
  prereq row. Gating it now would dim a step that works — DS-17b's defect, arrived at from the other side.
  **Receipt:** 14 backend tests + 5 in the rail editor; six mutants killed (no-verification-gate ·
  model-may-author-sql · chain-owned-visible-everywhere · both-keys-allowed · any-chains-query-visible ·
  switch-keeps-query_id); tree-wide ruff, `api.gen.ts` regenerated for the promote route, seven frontend
  gates green. ⏳ **The live end-to-end receipt is OWED** — it needs the API restarted onto this code.
  **The guard that keeps the law literally true:** `sql` is human-only. `automations/propose.py` may draft
  every field of a `trusted_query` step and is refused on that one, with a test that fails if a drafted or
  imported step ever carries it. A model may propose the QUESTION; a person writes the SQL. **The user's own
  argument for it, 2026-09-19, and it is the cleanest statement of the law in this document:** *"Never —
  thats the whole point. Investigate node exists separately to form its own SQL, etc"* — a node whose job is
  "a model writes the SQL" already ships and is governed as such, so a second one with none of that
  machinery has no reason to exist.
  **Falsifier:** a save path that arms a query which never executed · a model-authored `sql` reaching a
  stored automation · a private query whose verification or approval lives anywhere but the trusted-query
  store.
  **Receipt:** SQL typed on the node, verified on save, running on schedule while absent from the catalogue
  picker, then promoted by one click and picked by a second chain — with the stamp resetting, in front of the
  person who made it, when the SQL is edited.

- **DS-17b · The palette ranks what this deployment can actually run — ✅ BUILT 2026-09-19.** Item 26 (e), taken
  separately at the user's direction and FIRST — because it is a defect and the other two are features.
  🔑 **The ranking alone did NOT fix it, and the mutation run is what said so.** The first cut sorted available kinds
  above gated ones and looked right; its falsifier stayed green against the pre-fix sort, because the fixture had
  given every gated kind the highest priority so both orders agreed. Re-drawn on the measured live shape — `notify`
  (30), `brief` (40) and `integration_call` (70) are gated and sit ABOVE four runnable kinds — the arithmetic came
  out flat: **`trusted_query` is the 9th of 10 action rows under BOTH orders**, so the same eight rows precede it and
  it occupies the same pixels. Ranking moved it exactly nowhere.
  **What the mechanism actually was:** the three multi-line prereq sentences above it. So the gated rows now collapse
  behind one counted line — "5 steps need setup" — which the ranking is what makes possible, by putting them
  contiguously at the end. The count is the signal the flat list never gave: a reader who cannot see those rows still
  learns they exist. Not while searching, because a row hidden behind a fold when the person typed its name is the
  original defect with a lid on it.
  **A second defect found in passing:** the sort ran priority BEFORE search score, so typing "trusted" ranked
  priority-10 "Notify" (which merely says *trusted* in its description) above the priority-90 "Trusted query" just
  named. Relevance now leads; it is inert on an empty query, so it changes exactly the case it is about.
  **Receipt, taken live 2026-09-19** on the `workspace` connection at :3000: the Actions list renders five runnable
  rows and one fold, whole and without scrolling, with "Trusted query" fifth and usable where it had been ninth;
  the fold opens to the five gated kinds, each keeping its sentence. 26 tests, four mutants killed
  (no-availability-key · priority-before-relevance · collapse-while-searching · fold-open-by-default), seven
  frontend gates green.
  **Original note.** `palette.py` sorts by a static weight,
  so a kind whose prereq is unmet on this connection ranks as if it were available, and the sentence explaining why it
  is dimmed can fall below the fold. Available kinds sort above gated ones; the gated ones keep their sentence and
  their door; the order within each group is unchanged. Numbered DS-17b rather than DS-20 because it belongs to the
  first movement's palette work, not to this movement's two waves.
  **Falsifier:** the measurement that produced this item, re-run — a connection with no trusted queries where
  `trusted_query` still outranks a kind that connection can run today.
  **Receipt:** the LuxExperience Automations palette, where the gated kinds sit below the runnable ones and "Trusted
  query" no longer reads as absent.

- ✅ **DS-18a · a synthesis may leave the platform, grounded in the rows it read — BUILT 2026-09-19, §6 item 27
  decided the same day.** Found by
  building the first real chain on the new steps (theLook, 2026-09-19): `trusted_query` → `synthesize` →
  `slack_post` runs green and the send is **HELD at departure**, permanently, for a reason no amount of
  authoring can fix. HB-2 law 1 requires every stated magnitude to sit in *the measurement the message
  departs on*, and `departure_basis` builds one only from an `investigation_id` or an alert
  (`govern/departure_basis.py`'s `measurement_for_*` family). A `synthesize` step publishes `answer` and no
  measurement, so **a step whose stated purpose is "delivered either in Inbox or slack or practically
  anywhere" can never deliver.** The wave is incomplete without this, and it is deliberately NOT patched
  here: widening what may leave the platform is a governance decision, not a builder's.
  🔑 **The proposal is in-pattern rather than an exception**: a `measurement_for_synthesis` builder beside
  its siblings, whose `values` are the numbers in the rows the answer was grounded in, `source` the trusted
  query, `measured_at` its execution, and `remeasure` a re-run of that query. The warrant is arguably
  STRONGER than an analysis's prose, because `check_grounding` has already proved every number in the answer
  is present in those exact rows, and the rows came from a query verified on save (DS-19).
  **Two holds were measured on the live chain, and only one of them is this gap:** law 2 wanted an approved
  definition (`units_sold` on theLook is `draft`; `revenue` is approved) — that is the user's ordinary
  metric call, not a gap. Law 1 is the gap.
  ✅ **SHIPPED AND DEPARTED 2026-09-19.** `measurement_for_synthesis` sits beside its siblings; `synthesize`
  publishes the values its answer was written from on an internal key (`DISAGREEMENT_KEY`'s precedent — engine
  →gate plumbing, never a port on the canvas); the dispatch site reaches for it LAST, so an analysis, a promise
  or a finding always wins. Three calls inside it, each the harder way on purpose: `rendered` stays **False**,
  because True asserts grounding by construction and the construction here includes a model — law 1 therefore
  re-checks every magnitude at departure, a second independent pass over `check_grounding`'s · `remeasure` is
  **None**, because re-running the query would check fresh rows against sentences written about the old ones
  (moved data makes the answer WRONG, not stale, and `stale_note` says so) · the basis covers only the rows
  the MODEL saw, since an answer cannot cite a row it was never given.
  🔴 **The live run taught the tests one thing:** numeric STRINGS count. BigQuery hands `count(*)` back as
  `'75'`, so a basis walking only ints and floats would have held exactly the figures a person most wants to
  send.
  **Receipt, live on theLook:** `state: departed`, nine laws each with its verdict — `definition: cites metric
  units_sold v1` · `remeasure: 6 numbers grounded in the rows of top_sellers.rows, measured moments ago` ·
  `claims: descriptive — no associational, causal or forecast claim`. The message reached `#aughor_canvas` as
  TheLook Analyst (ts 1789820966.806669). 24 tests, five mutants killed.
  🔑 **And one hold was the author's own wording, which is the gate working.** The `context` instruction
  written to PREVENT a misleading claim — "the product ranking is driven by unit price rather than demand" —
  was itself read as a causal claim by `check_claim_type` and held the send. Reworded to state the fact
  ("each sold 1 unit for 903.0") the hold cleared, and the sentence reads better: the reader draws the
  conclusion instead of being handed one the analysis had no licence for.

**The order, as the user set it** — DS-17b first, because a fix for a defect should not wait on a feature; then
DS-19, which gets the SQL in; then DS-18, which turns it into something worth delivering. The pair is what closes the
user's sentence; DS-17b is what stops the next capability from reading as missing.

**Not this:** a Python node (item 1 and 2 above stand) · an expression language on bindings (`dataflow.py:58`)
· a second STORE for queries — an inline query is private to its chain (item 26 (c)) but is still a row in the
one trusted-query store, because scope is a flag and custody is not · a `synthesize` that re-derives a governed number instead of reading it (`metric_value` exists and is
the governed answer) · a model that authors SQL into a saved automation.

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
- **A verdict pins its evidence.** Graded runs become permanent; ungraded exhaust keeps
  expiring on the 14-day sweep. Retention follows grading, not the other way round.
  ⚠️ **Amended 2026-09-20 (MI-2b).** That sentence was true of `session_events` and false of the
  trace plane it has been read as describing: `events` had no sweep at all — 430,768 rows, 95 days,
  76.8% of them past the point `aughor_ops` can see. The journal's rule is therefore the INVERSE,
  and for a stated reason: there is no pin on `events`, so every kind is exempt unless it is named,
  and only `job.state` and `automation.run` age out.
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

#### MI-2a · The journal had no sweep at all (substrate-sized) — ✅ BUILT 2026-09-20; ✅ **MERGED #532** (`d91fb9be`) with its follow-up `a45ad258` — this header read "BRANCH ONLY" after the merge, corrected 2026-09-21

> **MI-2 fixed the sweep that was not running. This band found the table that had no sweep to run.**
> MI-2's law above — *"ungraded exhaust keeps expiring on the 14-day sweep"* — was written about
> `session_events` and has been read ever since as a property of the trace plane. It was not.
> `events`, the journal, is ~40× that table and had **no retention at all**: measured live
> 2026-09-19, **430,768 rows back to 2026-06-16** (95 days) in a 247 MB `system.db` with a freelist
> of zero, growing **8,475/day on 09-11 and 23,287/day on 09-18**. 🔑 **Third instance in a fortnight
> of §5's own lesson** — a prose claim inside §3 rots silently — and it rotted in the direction that
> matters, because retention is a stated privacy property that §6.4's and §6.7's custody decisions
> lean on. §3.9's catalogue-timestamp discipline is what caught it: the figures in this arc are
> dated 2026-09-02, and re-measuring them is what opened the table.
>
> **Unbounded growth was not the finding. Unreachability was.** `AughorOpsConnection` — the
> platform's own *"ask SQL about your own runs"* surface — snapshots the NEWEST 100,000 rows per
> curated table (`db/connection.py:1360`, `_SNAPSHOT_ROW_CAP`; `events` is one of its four, `:1355`),
> so what the journal cannot fit under that cap is not merely old, it is **invisible to
> self-investigation**. The oldest visible event was **5 days back**: **330,768 of 430,768 rows —
> 76.8% of the history — could not be queried by the platform at all.** What filled the window was
> chatter, not evidence: over one week `job.state` (94,926) and `automation.run` (31,494) were
> **99.1% of all events**, from five automations that ticked 30,470 times and fired 198. The table
> MI-1 grades from was 40× the size of the log MI-2 protects and carried almost none of the signal.

**Retention is SCOPED, and its default is the INVERSE of MI-2's — deliberately.** `session_events`
may sweep broadly because `pinned_at` exempts what matters; `events` has no pin, so **the exemption
has to be the default**. `events_prune` names the kinds it may delete (`AUGHOR_EVENTS_PRUNE_KINDS`,
default `job.state` and `automation.run`) and touches nothing else — a kind not named there
(`investigation.created`, `investigation.completed`, `ontology.build`, `agent.handoff`, …) is kept
forever. Deleting evidence to save space would be the wrong trade; deleting a heartbeat nobody reads
is free. The two-policy shape — an age window plus a row cap — is `session_events_prune`'s unchanged,
because a second retention idiom would be a second thing to reason about.

**The 2-day default is not a round number.** It is the largest window that keeps the WHOLE signal
history inside the 100k snapshot. Projected against the live table 2026-09-19: **1 day → 62,223 rows
kept · 2 days → 85,134 · 3 days → 108,048 (already over the cap) · 7 days → 165,855.** Signal alone
is 30,419 rows and spans all 95 days, so under a 2-day ops window **every semantic event ever emitted
becomes visible to `aughor_ops` again.** The row cap (`AUGHOR_EVENTS_OPS_MAX_ROWS`, 50,000) is what
makes that durable: an age window alone re-breaks the moment the tick rate rises, and it has been
rising — 8,475/day to 23,287/day in seven days. Capping the chatter at a fixed budget makes the
snapshot's headroom a property of the design rather than of today's traffic.

**Bounded per sweep, and driven by `emit` rather than by MI-2's counter.** 20,000 rows per sweep, one
sweep per 500 emits, plus the open-time insurance MI-2 built — with its own `kv` stamp
(`events_last_pruned_at`) in its own `try` block, so neither sweep can be the reason the other is
skipped. Two things MI-2 could not have known. First, the journal takes **~50× the writes**
(~23,000/day against the session log's ~450), so the identical counter of 500 fires about every
twenty minutes here and about once a day there — hung off the session-log counter, a 20,000-row
bounded sweep would have needed over two weeks to drain the backlog it exists to drain. Second, a
full batch is **not** stamped: stamping a bounded sweep that hit its bound would put the next attempt
six hours away, so a full batch means *come back immediately*. An unbounded first DELETE was never an
option — it runs inside `Ledger.__init__` against a ~350,000-row backlog, and work that raised there
has already cost this store a no-boot once (Migration 10, the same incident MI-2 cites).

**Migration 12 — the journal gets indexes on the two columns it is actually asked about.** It carried
ONE, `events_kind` on `(kind, seq)`. `trace_id` was added by **Migration 6** with a `DEFAULT ''` and
no index, and `emit` has stamped it from the ambient run on every call since — so *"everything that
happened in this run"*, the question the column was added to answer, **has been a full scan of the
whole table for its entire life.** `at` is what the new sweep filters on, every pass; adding retention
without it would trade unbounded growth for a scan at every open. Three indexes:
`events_trace (trace_id, seq)`; `events_kind_at (kind, at)` because the sweep's predicate names both
columns; and `events_at (at)`, because the composite cannot answer a bare time range on a
non-leftmost prefix. Portable SQL only, one statement per `execute`, every one `IF NOT EXISTS` —
Migration 11's rules, unchanged. ✅ **Numbering verified against the standing rule, and clean:**
`PRAGMA user_version` on the deployed `data/system.db` read **11** on 2026-09-19 and `_MIGRATIONS` in
`kernel/ledger.py` tops out at 11 on main, so 12 is both next-in-file **and** next-to-execute — the
two are not always the same number, which is the whole reason the rule says to number off the LIVE
store. No collision with the repo's eight other migration lists: each store is its own DB file and
therefore its own `user_version` namespace (`automations.db` at 9 · `agents.db` at 7 · `history.db`
at 6 · the proposal inbox at 5 · `audit.db` at 3).

**Two more, both found while measuring, and both the same shape — a fallback nobody could see.**

- 🔑 **The store facade's fallback was silent.** Every handler in `util/json_store.py` was a bare
  `except Exception: pass`, which made **the most dangerous state the only unobservable one.** The
  legacy file is a one-time import the healthy path never rewrites, so it goes stale the moment the
  store is used: measured live 2026-09-19, `schema_profiles.json` was 211,920 bytes last written
  **five weeks** before the 6.2 MB of ledger rows it stands in front of, and `agent_runs.json` held
  **1 run against the ledger's 220**. A read that quietly falls back does not degrade — **it
  time-travels.** A write is worse: the `migrated:` marker is already set, so the import never re-runs
  and the fallback's write is orphaned there permanently, with nothing in the codebase reconciling the
  two. Now counted and logged through the existing `tolerate` seam — one counter per operation,
  `json_store.ledger_fallback.<op>` — and **still never raising**: the best-effort contract is
  unchanged, the fallback simply leaves a trace instead of none. This is §0's *honest-signalled*
  substrate clause applied to the one path that had no signal at all.
  🔑 **The helper is module-level, and that is load-bearing.** The two facade families share no base —
  `LedgerListStore` descends from `JsonListStore`, `FileFamilyStore` from `KeyedJsonStore` — so as a
  method on one of them the other's handlers raised `AttributeError` **from inside an `except`
  block**, turning the tolerated fallback into the crash it exists to prevent.
- 🔴 **The outbound delivery log moves to the Ledger — and being a file is what hid a live failure.**
  `data/action_logs.json` was left file-first when the triggers moved, on the reading *"per-instance
  episode detail, not configuration"*. That reading is what hid the problem: it is the record of
  **every outbound send the platform has ever made**, a security surface rather than episode detail,
  and nobody queries a file. Opened on the live install 2026-09-20: **336 rows, 336 of them
  `status: failed`.** Every outbound delivery on that install had failed, unnoticed for as long as the
  file had existed, next to a properly indexed **61,696-row `audit_log`** that anyone would have seen.
  It is also the shape a file store serves worst — append-only and growing, read in full by
  `list_logs` and sliced in Python, no index, no time range. `LedgerListStore` gains an `append` that
  is **one INSERT**: the inherited one is `all()` + `save_all()`, i.e. `kv_replace_all`, a DELETE of
  every row followed by a re-insert of every row **per append**, on the one shape that grows.
  `log_id` widens from `uuid4()[:8]` to a full uuid because it is now a kv primary key — 32 bits is
  ~1% collision odds across 10,000 sends and better than even by 80,000, and an audit row silently
  overwriting another audit row is not worth 24 bytes. An item with no id gets a synthetic
  `__anon__:<uuid>` key, because `_key` renders a missing id as the string `"None"` and every id-less
  append would otherwise overwrite the last — the opposite of append-only, and deferring to
  `super().append` does not avoid it, because the parent body calls the two methods this class
  overrides.

**Receipt: proved against a COPY of the live database, not a fixture.** 451,617 rows → **75,685**; all
**375,932** deletions chatter; signal **30,419 → 30,419, unchanged**; the oldest visible event moved
from 2026-09-15 back to **2026-06-16**; and signal visible inside the 100k snapshot went from
**1,031 of 30,419 (3.4%) to all of it.** Every other table byte-identical, `PRAGMA integrity_check`
ok. 🔑 The two row counts corroborate the growth rate rather than contradicting it — 451,617 − 430,768
= 20,849, one day apart against a measured 23,287/day. Held by **29 tests**:
`tests/unit/test_events_retention.py` (20 — a semantic kind survives however old, only the named kinds
are swept, each of the three env knobs, both halves of the two-policy shape and each disabled alone, a
sweep never exceeding its batch, successive sweeps draining the backlog, a full batch NOT stamped so
it retries, the open-time sweep, the two stamps being distinct keys, `emit` driving the counter and
firing on the boundary, a failing sweep never breaking the write that triggered it, and the three
indexes present AND the sweep's predicate planning through one) and
`tests/unit/test_json_store_fallback_is_loud.py` (9 — a per-operation counter on every keyed and every
list method, the reason naming the file being served, the file contents still returned, append writing
one row without rewriting the store, insertion order preserved, and an item without an id staying
append-only).

⏳ **Not done, and this is the honest half.** ① None of it is on `main`: `3b642c2a`, built 2026-09-20,
merged into `claude/jev-align-and-traces-storage` at `9298316e`, **no PR opened** — this line must be
re-measured when it merges, per IP-4's lesson. ② **The 336 failed deliveries are a live defect this
commit made VISIBLE and did not fix** — nobody has yet asked why every outbound send on that install
failed, and the answer is worth more than the storage change that surfaced it. ③ The three env knobs
(`AUGHOR_EVENTS_PRUNE_KINDS` · `AUGHOR_EVENTS_OPS_KEEP_DAYS` · `AUGHOR_EVENTS_OPS_MAX_ROWS`) are
tuning, not store paths, so MI's store-hygiene law does not bind them — verified by precedent rather
than assumed: `AUGHOR_SESSION_LOG_KEEP_DAYS` appears in neither `tests/conftest.py` nor
`scripts/dump_openapi.py` either.
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

(after MI-3's block, before `#### MI-4 · First distillation`)
============================================================

#### MI-3a · The decision corpus: a row that knows which world it was made in, and an outcome that can come out negative — ✅ BUILT 2026-09-19/20 (`e68beffa` · `2174fc48` · `79d01b44`)

> **Origin.** `docs/JEV_ALIGN_STUDY_2026-09-19.md`, finding **A1** (§3.20) — the smallest diff in that
> study and the one needing no vendor and no model. **The store itself is not new and has never been
> recorded in this document:** `record_decision` and the `decision_record` table landed on main with
> #526 (squash `e65b9d17`, 2026-09-18), giving `mark_outcome`, `list_for_export`, `site_stats` and
> three registered sites. This wave is what A1 adds ON TOP of them.
>
> **The premise, measured on the live store 2026-09-19 — three columns, none of them usable.** 40
> rows, all from ONE of the three sites (`converse.tool`); the other two (`ask.route`,
> `framing.definition`) had produced nothing on this deployment. Every row `conn_id = ''`. Every row
> `confidence = 0.0`. And `outcome` = **`'ok'` on 40 of 40**, because its only writer was
> `tool_loop.py:226`'s inline *"the tool did not raise"*. 🔑 **The column is not empty, it is
> CONSTANT** — a label that never takes its other value carries no information, and what it records is
> that the tool RAN, not that the pick was RIGHT, so `exporters.list_for_export` would have shipped 40
> positive examples into MI-3's plane. `mark_outcome` — the seam that exists to write the real outcome
> once the answer is judged — had **zero call sites** outside its own tests. (The study's first draft
> reported `outcome=''`; that was a misread of an unlabelled sqlite column, and it is corrected in
> place rather than deleted — `df98b8fb`. The corrected finding is the sharper one.)
>
> **Built unconditional: no prompt change, no behaviour change.** `record_decision` takes `inv_id`;
> `decision_record` grows the column additively and 🔑 **its index is created AFTER the ALTER rather
> than inside `_DDL`** — `executescript` runs first, so an index over `inv_id` in the DDL takes down
> every pre-existing store. Caught by running the new harness against a SNAPSHOT of the live one, not
> in review. All three sites now carry `conn_id`/`trace_id`/`inv_id` (`nodes.classify_question` behind
> optional kwargs so `ask_router` keeps its signature, `run_tool_loop` threaded from both callers,
> `choose_definition` threaded through `resolve_frame`/`frame_from_state`). `mark_outcomes_for_run`
> closes every decision a run made, driven from `record_verdict` on **reject** and **correct** — the
> first caller `mark_outcome` has ever had. **`accept` deliberately does NOT propagate:** a right
> finding does not establish that any individual pick inside it was right.
> **A correctness fix the verify pass turned up:** `ask.route` had been recording the model's
> confidence against the FINAL route — the model said 0.4 about "direct", the 0.65 floor then moved the
> route to "investigate", and the number described a different answer. An overridden route now records
> `source=rule` with no probability, and the test that had pinned the old behaviour says why.
> **The ordering defect, found by running two real turns** (`79d01b44`): the four `converse.tool` rows
> carried `conn_id` and an EMPTY `inv_id` — attribution with no way to ever close it — because a chat
> turn has no investigation id while it runs; `save_chat_turn` mints one FROM the answer. The loop now
> records against a trace the router chooses up front, and `decisions.attach_run` stitches the
> investigation on once it exists, filling **only empty** `inv_id`s so a later turn sharing a trace
> cannot reassign a decision that already belongs to a run. Re-run after the change: 5 rows, all
> carrying `conn_id` + `trace_id` + `inv_id`, and `mark_outcomes_for_run` can now reach them.
>
> **The measurement** — `evals/decision_yield_eval.py`, the first eval here that scores the RECORD
> rather than an answer, over `decisions.corpus_yield` (attributable · with_probability ·
> discriminating · trainable, the last keeping `list_for_export`'s own floor so the two reads cannot
> drift). **No model call and no warehouse**, so it is free and safe to run often; read a live store
> through a `.backup` snapshot, never in place. Arm A is DERIVED PER SITE (`_ARM_A_CAPABILITY`), not as
> a blanket zero — `ask.route` always passed the model's confidence, so the probability column is not
> what A1 bought there, and an unknown site is assumed arm-A-capable so a new site cannot flatter the
> result by being missing from the table (`2174fc48`, which corrects an overstatement of A1 and says
> so in its own subject line).
> - *Baseline, live 40 rows, 2026-09-19:* 0 attributable · 0 with a probability · outcomes `{ok: 40}`
>   · **falsifier FIRES**, as it must on rows the old code wrote.
> - *Arm B, 8 LuxExperience questions through the instrumented router* (gemini-3.1-flash-lite,
>   hermetic scratch store): `ask.route` attributable **0 → 8**, with a probability 8 → 8,
>   discriminating **False → True** on `{rejected: 1, corrected: 1}`. **Falsifier HOLDS.**
> - *Arm B on the conversational path, 2 real LuxExperience turns, 2026-09-20:* `converse.tool`
>   attributable **0 → 5**, with a probability 0 → 0 (the loop passes none, by design), outcomes
>   `{ok: 5}` after two truthful `accept` verdicts. **Falsifier HOLDS on attribution alone.** Both
>   turns answered correctly against the warehouse (783 cancelled FY2025 orders and 26.2% of order
>   lines returned, against 783 and 26.19% measured directly), so `accept` was the honest verdict.
>
> 🔑 **Two findings worth more than the pass.** (1) **The router returned confidence 1.00 on all eight
> questions** — including lb11, the one both models in the ON-10 receipts got wrong. The probability
> column is populated and **FLAT**, so the uncertainty-scheduling half (study finding A2) has an input
> that cannot rank anything. That is a calibration finding on real traffic, not an assertion, and it is
> the gap the companion study already named: nothing here checks that 0.6 means 60%. (2) **The negative
> class only ever arrives from failures**, because `accept` does not propagate — so on a mostly-correct
> system this corpus is heavily imbalanced by construction. Both are properties MI-4's gates will be
> counted against, and both are better stated now than discovered at the gate.
>
> ⚠️ **A flag registered whose ON arm has never executed — recorded as a finding, not as readiness.**
> `framing.choice_confidence` (`kernel/flags.py`, env `AUGHOR_FRAMING_CHOICE_CONFIDENCE`) asks the
> definition chooser for its own number through a SEPARATE response model
> (`DefinitionChoiceWithConfidence`), so the off-arm ships today's schema byte-identically — it is an
> `EXPERIMENT` entry in group D, because adding a field to a response model changes the prompt. Its
> grid is marked **GRID BLOCKED ON CORPUS**, premise-checked 2026-09-19: `choose_definition` runs only
> on an ambiguous frame (`chosen is None and len(candidates()) > 1`, where `candidates()` keeps only
> `usable` outcomes), and **all 32 authored LuxExperience questions frame to 0 ambiguous** — 27 reach
> no usable candidate, 5 reach exactly one — measured through the read-only `POST /ontology/frame`,
> no model and no warehouse. So the flag is registered, the second response model is written, and the
> ON arm has run on **not one** authored question; a grid would buy a no-op on every case, which is
> exactly what `explore.route_wide` is parked for. 🔑 This is the #530 shape one plane over — a guard
> that never saw what it gated — and the register is where it has to be visible, because a flag that
> reads as an experiment-in-progress is how one stays parked for a quarter.
> **UNBLOCK:** author a set whose questions fit TWO executable declared measures on one connection,
> then grid the fired subset. **EXIT once fired:** graduate if agreement is unchanged within noise AND
> the recorded confidence is lower on overturned picks than on upheld ones; **DELETE the flag and the
> second response model if the number is flat**, because a probability that does not separate cannot
> rank a queue and study finding A2 then has no input at all.
>
> **Held as tests:** `tests/unit/test_decision_yield.py` (the seams hermetic, including that an EMPTY
> store reads INCONCLUSIVE rather than as a pass) and `tests/unit/test_decision_records.py`. The full
> suite caught one collateral failure — two tests stubbed `classify_question` with a positional-only
> callable — fixed in `0475c1ed`; 11,273 passed, 5 skipped, 1 failed before, green after.


============================================================
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

#### The second movement — authoring by sentence (adopted 2026-09-15, §6 item 22 (a); SP-7 STARTED the same day)

> **Origin.** The user, 2026-09-15: *"Tell me if I can create automations or agents via natural language on
> Aughor.. and if not draw me a proper roadmap"* — then drove the answer themselves through ⌘K, *"create an agent
> that delivers anomalies to slack every morning at 9am"*, and sent the transcript with a screenshot: *"the
> formatting in the spotlight is not very great as well as the presentation... must feel agentic.. it is honest -
> which is nice"*. The measured answer and this plan were published as the artifact "Authoring by Sentence"
> (https://claude.ai/artifact/Eiw3AWUFrizWGS783fZmdf); the user adopted it in one sentence: *"yes add it to the
> roadmap and start SP-7"*.

**What is true today (measured 2026-09-15 — read-only against the running API, main `61cba06a`, no model calls):**

- **Four doors draft from words; none creates.** Create agent → Describe (`CreateAgentFlow.tsx:58` →
  `POST /agents/custom/propose`, drafted inside the connection's real catalogue) · Automations → Propose
  (`automations/propose.py:234`, validated and dry-run) · Spotlight's `draft_agent`, `draft_automation`,
  `pause_or_resume_automation` and `propose_agent_grant`, staged on the one inbox — from chat, ⌘K and Slack only while
  `ask.converse` is on (code default OFF, `kernel/flags.py:270`; ON at the user's deployment by a runtime override),
  and from any MCP client through `/spotlight/tools` with no flag. The Quick chip posts `/chat`, which has no tools.
- **The user's sentence staged two proposals** on theLook (`8233e4fd`): `b101b8ed` (agent draft) and `ce470b60`
  (automation draft). Read from the live inbox and left untouched, they carry six breaks:
  1. the answer is a wall of prose — `web/` has no markdown renderer, so lists run inline and backticks print, and
     hyphen-digit runs inside the proposal id and the date render in the adverse red; the drafts are described, not
     handed over as things to open or approve;
  2. the approval rows print `JSON.stringify(p.params)` (`AutomationsPanel.tsx:749`), and the Attention row offers
     Accept and Reject with no view of what either creates;
  3. the agent is pinned to schema `public` on a connection whose schema is `thelook` — `validate_agent_draft`
     (`custom_agents/store.py:147`) never reads `schema_scope`, and `_apply_agent_bindings`
     (`routers/investigations.py:5486`) forces every ask made as the agent onto it;
  4. the agent and its schedule never meet — `draft_automation` takes only an outcome, so the chain's investigate step
     carries no `agent_id` and runs as the default agent;
  5. Accept arms, on a UTC clock — the draft carries no `enabled`, `Automation(**params)` defaults it to True
     (`automations/models.py:407`), cron is read in UTC and an automation has no timezone; and a declared write inside
     a chain runs unattended unless `AUGHOR_ACTION_APPROVAL` is set (`govern/actions.py:71`);
  6. a placeholder validates — channel `#general`, sender TheLook Analyst. Spotlight asked the user to confirm both
     "before arming", and Accept does not wait for that.
- **Also measured:** the guide sends a person to an "Agents page → New agent" (`agent/spotlight_guide.py:146`) where
  the rail says Agent Ops and the button "+ Create agent", and to a "Connections page (the plug icon in the sidebar)"
  the rail does not have — connections live in the Catalog, and the plug is Integrations; Accept records the name the
  page sends (`body.actor`: "operator", "control-room"), not the signed-in person; no tool drafts a monitor or a brief
  subscription; there is no email sender.
- **Adoption, measured:** across nine connections' inboxes, four Spotlight drafts ever — the two 2026-09-06 receipts
  (both rejected) and the user's two — and none accepted. The user's follow-up, *"Take me to the agent ops.. I will
  enter the details there"*, is SP-3's own falsifier arriving as data: a draft abandoned for the form.

**The laws the movement keeps** are the arc's, unchanged: every structural write stays a proposal — the model drafts,
a person certifies · one inbox, one scheduler loop, one declared roster, with routing left to the tools' own
descriptions and no intent classifier · an agent stays a form, never a canvas (§4.1); only the chain is drawn ·
credentials never travel through chat · no model id in `aughor/`, and no model grades its own drafts.

**SP-7 · Honest drafts — ✅ BUILT 2026-09-15** (session branch `claude/aughor-nlang-automations-roadmap-3ffcee`,
not merged; the live receipt waits on the user). A draft may only say what is true on this deployment.
- A drafted agent names a schema its connection has, or none. It is refused where the schemas are KNOWN — the
  connection pins one (the catalogue's own filter, `routers/catalog.py:46`), or the caller holds the measured
  catalogue; with neither, nothing is refused, because a failed probe is not an absence.
- A choice only the person can make stays open instead of being guessed: a Slack channel the request did not name, and
  a sender when more than one bot could post. The chain still validates (the import funnel's two passes,
  `routers/automations.py:283`), is staged with its open choices listed, and Accept refuses — leaving the proposal
  pending — until a draft fills them.
- The first run is stated with its date, in UTC. *Re-scoped at the start: local time moves to SP-13, because the
  reader's timezone is not known on the server — the settings registry has no such key.*
- A declared write drafted into a chain waits for a person on every run, whatever `AUGHOR_ACTION_APPROVAL` says; a
  person's standing grant for that exact target still satisfies it.
- The guide names what is on screen, and a parity test pins every quoted label to `web/`.
**Receipt:** the user's sentence asked again — no `public`, no `#general`, Accept refused while the channel is open,
the first run stated, and every label the guide quotes found in `web/`. **Needs:** nothing.

> **Built 2026-09-15 (five commits on the session branch).** Measured at the start and folded into the wave: a
> new schedule fires on the scheduler's NEXT TICK, not at its cron time — `engine._schedule_fired` answers "first
> run" when there is no previous run — so the user's 9am chain would have posted within a minute of Accept. An
> accepted all-schedule draft now waits for its first scheduled time through the mute that already exists
> (`paused_until`), stated in UTC by the scheduler's own trigger (`engine.next_fire_utc`). What landed:
> - **Schema** — `custom_agents.store.schema_scope_problem`, in the one validation body every door runs
>   (Spotlight's stage, the inbox accept, create, patch, from-template); it refuses only where the connection pins
>   its schema or the caller holds the catalogue.
> - **Open choices** — the drafter blanks a Slack channel the request did not name, and a sender when more than one
>   bot could post; `fill_required_holes` (now shared with the import funnel) names them; the inbox refuses Accept
>   BEFORE its resolve-once update, so the proposal stays pending; Propose and Spotlight return `to_fill` and
>   `first_run`.
> - **Drafted writes wait** — a declared write a model drafts carries `require_approval`, and the executor asks a
>   person on every run whatever `AUGHOR_ACTION_APPROVAL` says; an accept or a standing grant still satisfies it.
> - **The guide** quotes real labels (“Agent Ops” → “+ Create agent” → “Describe”, approvals under “Attention”,
>   “Catalog”, ⌘K's “Add a data source”), held by a parity test over `web/`.
> **Receipts:** `test_sp7_honest_drafts.py`, `test_sp7_drafted_writes_wait.py` and `test_sp7_guide_labels.py`, with
> the neighbouring suites and every ratchet green; the full backend suite ran once on `53047981` — **10,165 passed,
> 5 skipped**. **Open:** the live receipt — the user's sentence asked again through
> the running product, which needs the API restarted on this code and spends model calls, so it waits on the user's
> word. The user's two drafts of 2026-09-14 predate this code: after a restart the agent draft refuses at Accept (its
> schema), but the chain draft still names `#general` — a value, not an open choice — and would be accepted as it
> stands, so it should be rejected by hand.

**SP-8 · Agent + its schedule — ✅ BUILT 2026-09-15** (session branch `claude/sp-8-9-agent-bundle-approval-card`, with
SP-9; the live first-run receipt waits on a deployment running this code). "An agent that does X every morning" stages
ONE proposal holding both records; Accept creates the agent and then saves the chain with its `agent_id`, all or
nothing. `draft_automation` may also name an existing agent, so a chain can run as one without a bundle.
**Receipt:** one proposal for the user's sentence, and the first run's receipt and spend attributed to the new agent.
**Needs:** SP-7.
> **Built 2026-09-15.** `draft_agent` gained `schedule` — the ask's own when/where clause — and stages the
> `agent_bundle` kind: params hold BOTH records, the chain names NO agent id (the accept sets it from the record it
> just created, never trusting a claim about one yet to be born), and a chain save that fails DELETES the agent it
> just made, so a half-married pair cannot exist. A chain proposer refusal refuses the whole bundle: an agent staged
> beside a refusal is exactly the half the kind exists to prevent. `draft_automation` gained `run_as_agent` (an
> EXISTING agent, id or exact name; another connection's agent refused with its home named; an unknown name is a
> refusal, never an invitation to invent one) — the saved chain carries `agent_id`, which VA-9b's `acting_agent`
> already reads for per-run attribution and spend. Driven over real HTTP on scratch stores with only the MODEL faked:
> the user's sentence staged one bundle, SP-7's blanking opened the unnamed channel, accept-with-fill created
> `ua_…` and saved the chain running as it, muted until its 09:00 first run; a second accept 409'd. The LIVE first
> run (receipt + spend on the new agent) needs a deployment on this code and a real tick — still owed.

**SP-7b · The hold widened to outbound sends — ✅ BUILT 2026-09-16** (branch `claude/drafted-first-send-holds`; the
user: *"this should be available for operations in the UI.. you should not be doing this"*). SP-7's law — a write a
model drafts into a chain waits for a person — covered warehouse writes ONLY, and a live 9am tick proved the gap: a
drafted anomaly chain's Slack post would have fired unattended, and my own claim that it would park was FALSE. Now a
drafted `slack_post` carries `require_approval` too, and the Slack dispatcher returns `approval_required` on its first
run unless a standing send-grant covers this chain and channel. The run parks on the same DS-8 machinery every declared
write uses; the parked step stages a new `outbound_send` inbox kind whose accept performs the post through the same
`post_as_bot` (so a resumed chain reads the real thread `ts` downstream), and whose "always allow" (the card's own
checkbox, minted only by a HUMAN's accept — never by the model, never by me) records a channel-bound standing send-grant
reusing `actions/grants.py`, owned by the automation and revoked with it. The card renders the destination and message
with the always-allow control in Attention, the inbox and chat — the affordance where the user said it belongs. `notify`
is deliberately excluded: it fires a webhook a person already stood up. **Receipt:** a drafted post parks, accept sends
once, always-allow lets the next run post unattended, and a hand-built post is untouched — all through the real engine
and inbox, `tests/unit/test_drafted_send_holds.py`. **Still owed:** the same hold for other outbound transports, and
the live tick on a deployment carrying this.

**SP-9 · The approval card — ✅ BUILT 2026-09-15** (same branch as SP-8). One card per proposal kind, the same in
Attention, the Automations inbox and chat: an agent's scope, schema and instructions; a chain drawn read-only on the
canvas with its first run, destination, runs-as, dry run and cost per run. Accept · Open in editor · Reject, with open
choices as fields to fill, and a link on every staged proposal. A ratchet: no proposal renderer prints raw params.
**Receipt:** the user's drafts read as cards in all three places, and `JSON.stringify(p.params)` is gone from the
approval rows. **Needs:** SP-7, SP-8.
> **Built 2026-09-15.** ONE `ProposalCard` (web/components/ProposalCard.tsx), kind-specific bodies, rendered in FOUR
> places: the Automations inbox, Attention (a proposal-backed row carries the whole card, replacing the blind
> Accept/Reject beside a title), the Actions rail, and chat — a turn that stages announces it on a new
> `proposal_staged` frame (emitted by the act tools when the streaming caller binds `emit`; None on every sync
> transport, declarations identical, parity held), and the chat fetches the RECORD by the new
> `GET /kinetic-actions/inbox/{id}` and renders the card with Accept inline. Open choices render as fields; Accept
> sends them as `fills` ({"<action>.<key>": value}) and the inbox applies a fill ONLY to a currently-open choice —
> anything else is refused whole as an edit dressed as an answer — then persists the filled params so the record
> shows what was ARMED. Proposals now carry stage-time `detail` (to_fill · open_choices · first_run · dry_run_ok ·
> runs_as; inbox migration 5, numbered off the live store's `user_version`=4). The chain is drawn as a read-only
> strip on the card (trigger → steps, the waiting step marked); "Open in editor" opens the REAL canvas seeded the
> DS-15 way — the deltas against the spec's letter: the full ReactFlow canvas is one click away rather than embedded
> per card, and **cost per run is NOT shown — the repo has no measured per-run cost source, and the card does not
> invent one** (a measured source is SP-12's "each option's cost shown" prerequisite). The ratchet
> (tests/unit/test_proposal_card_ratchet.py) bans `JSON.stringify(…params)` across web/ with one declared, checked
> exemption (the params EDITOR's text field); both prior dumps (AutomationsPanel, KineticPanel ×2) are gone. The
> frame-parity parser now reads the tool layer's emit sites too, so a tool-minted frame can no longer ship without a
> consumer. Housekeeping the ratchet's own law forced: the kinetic router's prefix is spelled ONCE
> (`APIRouter(prefix=…)`, wire identical), and the vocabulary baseline fell 328 → 319. Accept surfaces still send
> their own actor names ("operator", "control-room", "chat") — identity lands in SP-14.

**SP-10 · Show the work — ✅ BUILT 2026-09-15** (branch `claude/sp-9-overlay-card-declaration`, with the SP-9
parts-path fix). A turn that acts keeps its steps in view as they happen; the answer carries the proposal
cards themselves, built from the tool result rather than the prose, with live status; prose renders lists, inline code
and ids as copyable mono chips, and ids and dates are never tinted as figures; the honest caveats stay, as flags on the
card. **Receipt:** the user's ⌘K turn before and after, screenshotted — a visible trail, cards with Accept inline, no
literal backticks, no red hyphens. **Needs:** SP-9 and §6 item 22 (b).
> **Built 2026-09-15, the same evening the user photographed the overlay** ("The size of the Text the quality of the
> Text the overall interactive capabilities are absolutely terrible"). Three fixes, three causes:
> **(1) The card was invisible on the parts path.** Both chat surfaces (ChatPanel and the ⌘K overlay) render through
> `uiMessageAdapter`'s parts, whose own DECLARED list is a second gate the frame-parity test never read — the
> `proposal_staged` frame rode the escape hatch as "UNRECOGNISED: PROPOSAL_STAGED" with a projector sitting unused.
> Declared as a typed progress part; a regression test drives the WHOLE path (frame → adapter → SDK accumulator →
> projection), because the projector-level test could not fail on this.
> **(2) Prose.** Decision 22(b) taken as recommended: `AnswerProse` (react-markdown + remark-gfm — a maintained
> renderer, per the user's library-defaults rule) with a designed, allowlisted surface: lists render, headings become
> bold paragraphs (one type scale in an answer), inline code and bare ids are copyable mono chips, raw HTML and images
> never render, tables keep BriefProse's treatment. A multi-paragraph or markdown-structured answer now reads at body
> size (`readsAsProse`); a one-line conclusion keeps the display headline. The Briefing keeps `BriefProse`; both share
> ONE inline-figure rule.
> **(3) Red hyphens.** `renderEmphasis`'s signed-delta rule is bounded on both sides, so `-3f4d` inside a proposal id
> or a date's `-09` never again reads as a loss — a real `-$2.1M` still does. The chat card also polls while pending,
> so a proposal resolved on another surface settles on the card in chat (live status).
> **LIVE RECEIPT, the user's own hands, 2026-09-15 ~21:40:** minutes after the parts fix reached their dev server, the
> user's bundle `c0e1c05a` was accepted FROM THE ATTENTION CARD (resolved_by control-room): both open choices filled on
> the card (channel `all-luxexperience`, sender `tl_123`), agent `ua_6d903822bb54` "Anomaly Scout" created AND its
> chain `7082045c` saved running as it, muted until its first run 2026-09-16T09:00Z — SP-8's bundle and SP-9's
> fills-at-accept, exercised end to end on the live deployment. Still owed: the first TICK's receipt and spend
> attributed to the agent (09:00 UTC next morning; the drafted slack_post waits for a person on that run per SP-7 —
> approving it with "always allow" makes later mornings unattended), and the after-screenshot of a fresh ⌘K turn.
> **Also closed in passing:** `scripts/dump_openapi._isolate_stores` was missing FIVE stores (AGENTS · AGENT_ALERTS ·
> EVALS · MATCACHE · ORGS) — latent for the spec dump, but the helper also isolates live drives, and an SP-8 drive
> wrote two scratch agents into the live `data/agents.db` (found on the live roster; both deleted the same hour, the
> user's own records untouched). The list now carries the measured union and says to diff, not trust.

**SP-11 · Revise in place — ✅ BUILT 2026-09-16** (branch `claude/graph-finding-hygiene`, with the question-echo
finding fix). A follow-up supersedes the pending draft, so the inbox holds one pending proposal per ask;
Open in editor loads the draft into the real form, and saving there resolves the proposal instead of creating a second
record. **Receipt:** three follow-ups leave one pending proposal carrying all three changes, and finishing in the form
leaves no duplicate. **Needs:** SP-9.
> **Built 2026-09-16.** The inbox gains its fourth resolve verb: `superseded`, terminal, first-responder-wins like
> every resolve — a settled draft stays what a human made it. The drafting tools (`draft_agent`, `draft_automation`,
> the bundle) take `supersedes`: a corrected re-draft resolves the earlier PENDING draft on the SAME connection and
> says so in the summary; a settled or foreign id is refused with both records left standing, so a model cannot
> retire another conversation's work by naming its id. The editor's half: "Open in editor" carries the draft's
> proposal id, and the canvas's save resolves it as "finished in the editor as <automation id>" through the new
> supersede route — for a PLAIN automation draft only, because saving the canvas creates the chain alone and
> superseding a bundle would silently drop its agent half (a bundle's proposal stays pending for the card). The
> receipt sentence runs as a test verbatim: three follow-ups leave one pending proposal. LIVE receipt (a re-drafted
> ⌘K ask leaving one card) waits on the next deployment.

**SP-12 · Edit, monitor, brief — ✅ BUILT 2026-09-16** (same branch as SP-11). Change what exists by sentence — edit,
disable, delete — staged as a before-and-after
diff; draft a monitor and a brief subscription; for anomalies, prefer a monitor trigger that starts the deep analysis
only when something moves, with each option's cost shown. **Receipt:** "alert #ops when refund rate breaks 3σ" stages a
monitor and its chain, and "move the Monday brief to 8am" stages a one-field diff. **Needs:** SP-11.
> **Built 2026-09-16.** Three staged kinds, each the arc's custody unchanged (the model drafts, a person certifies):
> **`automation_edit`** — `edit_automation` computes a BEFORE→AFTER diff against the live record over a CLOSED field
> set (name · description · cron · enabled; structure stays the canvas's); the diff is the card; accept re-reads and
> re-validates through a registered edit door, so a staged edit can never save a chain the editor would refuse. A
> cron edit needs exactly ONE schedule trigger or it refuses to the canvas. `delete: true` stages removal on the
> state door instead (irreversible once accepted, and the summary says so); disable is `enabled: false`.
> **`monitor_bundle`** — `draft_monitor` stages ONE proposal holding the monitor (a REGISTERED metric or explicit
> SQL; unknown metrics refused with the known ones named; anomaly at Nσ, checked hourly) AND the chain its breach
> fires (deep analysis → Slack). Accept creates the monitor, injects its id into the chain's metric trigger and
> saves — all or nothing, the agent bundle's law: a rollback leaves no chainless monitor breaching silently. SP-7's
> blanking holds: an unnamed channel/sender stays an open choice the approver fills on the card. **The cost is
> stated STRUCTURALLY, not invented** (the repo still has no measured per-run cost source): the hourly check is SQL
> only and spends no model calls, and the analysis runs only on a breach, where a daily schedule spends it every
> tick — said in the tool's routing description AND in the staged summary the approver reads.
> **`brief_draft`** — `draft_brief` stages a briefing subscription (day, or week on Monday, at an hour UTC) through
> an EXISTING Notifications trigger; unknown triggers refused with the known ones listed; accept re-checks the
> trigger still exists before saving. Both receipt sentences run as tests verbatim. All three kinds render as card
> bodies (the edit as strikethrough-before → after rows), take accept-time `supersedes`, and audit as
> `spotlight.<kind>`. LIVE receipts wait on the next deployment.

**SP-13 · Your timezone — ✅ BUILT 2026-09-16** (same branch as SP-11/SP-12). A timezone key in the settings registry
and on each automation; the scheduler evaluates cron
in it; drafts and cards speak local time, and UTC stays visible for operators. **Receipt:** a 09:00 Europe/Berlin chain
fires at 07:00Z in summer and 08:00Z in winter, pinned by a test across the clock change. **Needs:** nothing.
> **Built 2026-09-16.** The receipt sentence is pinned VERBATIM, including the clock-change morning itself (Berlin
> falls back 2026-10-25; Saturday fires at 07:00Z, Sunday at 08:00Z, one day apart, no arithmetic of ours between).
> The ONE cron factory (`engine.cron_trigger`) takes the chain's clock and APScheduler owns DST; `next_fire_utc`
> ALWAYS returns UTC whatever zone evaluates, because every consumer stamps ISO with a Z and a Berlin-local datetime
> wearing a Z is the lie this wave exists to end. `Automation.timezone` ("" = UTC, every pre-SP-13 chain; IANA name
> validated at CONSTRUCTION — a typo'd clock refuses, never arms a 9am that fires at 7; migration 7, numbered off
> the live store's 6). The scheduler's due-ness, the store's first-run mute and the draft's stated first run all
> read the same factory. `timezone` joined the settings registry (drafts default to the caller's chosen clock) and
> the edit door's closed field set — "switch it to Europe/Berlin" is a one-field diff. Drafts speak local with UTC
> in parens; the card's First run row does the same (the Intl primitive lives in lib/format, REC-U8); the schedule
> editor labels the chain's real clock and suppresses its client-side next-run guess for any non-UTC zone — exact
> arithmetic only, DST is the server's. **Open, recorded:** the canvas SEED carries conditions/effects only, so
> finishing a zoned draft in the form saves a UTC chain (the same seed already drops a drafted runs-as — one gap,
> SP-11-adjacent); and SP-14's "drafts and cards" leftovers (Slack approval identity) are unchanged.

**SP-14 · On by default — ✅ FIRST SLICE BUILT 2026-09-16** (same branch; §6 item 22(d) decided "Graduate as-is").
`ask.converse` graduates on its receipt; approval from Slack buttons, recorded against the
approver's linked identity; Accept records the signed-in person rather than the name a page sends; MCP clients see new
tools without reconnecting (`tools/list_changed`) and get native parameter schemas (SP-5's open note). **Receipt:** a
fresh clone with no runtime overrides drafts an agent from ⌘K, and a Slack approval shows the approver's identity in
the audit. **Needs:** SP-12, SP-M and §6 item 22 (d).
> **Built 2026-09-16 (the graduation + the web identity half).** `ask.converse` moved from EXPERIMENT to
> FLAG_DEFAULT — default-ON with the flag KEPT, because its off-path is not dead code but the ineligible-turn
> fallback every converse turn still rides; the registry's own empty-set guard was narrowed to its real claim
> (nothing ELSE drifts back in), and every default-off contract test inverted its setup while keeping its point: an
> operator's explicit off still means byte-for-byte off. Exit evidence recorded on the disposition itself: SP-M's
> 26/26 honest drafts across two recordings, 81% correct behavior on the richer fixture, the step-budget residual
> accepted by the user as a cost knob. The web accept-identity half: every surface now records the SIGNED-IN
> person's email when identity is present (`approverName` in lib/auth), with the page's own name only as the
> unauthenticated fallback — "operator" / "control-room" / "chat" stop masquerading as people the moment identity
> exists. **Open, the wave's remainder:** Slack approval buttons recorded against the approver's linked identity;
> MCP `tools/list_changed` + native parameter schemas (SP-5's note); and the fresh-clone ⌘K receipt itself, which
> only a fresh clone can give.

**SP-M · Measure authoring (alongside every band) — ✅ BUILT 2026-09-16** (same branch as SP-11…SP-13). About thirty
real asks drafted once and recorded, then scored with
no model — it validates, names its open choices, binds runs-as, uses a real schema, gets the clock right, shows its
cost; staged → accepted → finished in the form → lapsed, counted weekly; SP-3's falsifier measured rather than assumed.
**Receipt:** the scoring runs in CI; the baseline on 2026-09-15 is 4 staged, 0 accepted. **Needs:** nothing.
> **Built 2026-09-16.** `aughor/agent/authoring_measure.py`, two model-free instruments: `score_proposal` grades a
> STAGED row against the movement's own laws (the chain validates · declared open choices == the accept gate's real
> holes, compared as parsed pairs · a bundle's chain carries no agent id at stage · a schema claim graded only when
> a catalogue is KNOWN, None otherwise — a failed probe is not an absence · the stated first run sits ON a cron
> boundary in the chain's OWN clock, so a recording scored months later grades the same · a monitor bundle states
> watches/σ/cadence). One test drafts through the REAL tool and scores the REAL row, so scorer and tools cannot
> drift. `authoring_funnel` folds staged → accepted → finished-in-form → redrafted → rejected → lapsed by ISO week;
> SP-3's falsifier is the `finished_in_form` column, keyed on the exact sentence SP-11's editor door stamps — a test
> pins the two ends together. The thirty-ask corpus is frozen (`evals/authoring_asks.jsonl`, six families including
> two refusal asks); `scripts/record_authoring_drafts.py` is the ONE spending step (scratch stores, live model,
> ~30–90 calls), run on the user's word — the recordings then score in CI for free. **Baseline RE-MEASURED live,
> read-only, 2026-09-16** (the 09-15 figure aged the same day it was written): **6 drafts ever staged · 1 accepted —
> the user's own bundle — · 5 rejected · 0 finished in the form · 0 lapsed.** The weekly count
> reaching a surface (Agent Ops) stays open.
> **THE RECORDING RAN 2026-09-16** (the user's word, ~60 model calls, scratch stores + live coder;
> `evals/authoring/recorded.jsonl` committed — scored in CI free forever). **The scored set's verdict:** every draft
> that STAGED is honest — 10 proposals across 5 kinds, zero check failures (validates 4/4 · open-choices 4/4 ·
> runs-as 1/1 · clock 1/1 · cost 3/3). The funnel's real leak is UPSTREAM: 21 of 30 asks staged nothing, in three
> measured classes — (1) honest refusals doing their job (both red-team asks refused; the pricing watchdog checked
> the warehouse FIRST and found no price data — exemplary); (2) considered proposer refusals on the sparse fixture
> (the brief/agent families — a fixture with bots and a briefing would move these); (3) ONE real defect, closed the
> same hour: exact-name resolution refused "Monday brief" against "The Monday brief" WITHOUT naming the candidates,
> so the model wandered the platform reads until the turn's budget died (a23 ended answerless at 8 steps) — the
> not-found refusals now list the connection's own automation/agent names, the movement's convention everywhere
> else. Open questions the numbers raise for SP-14's gate: the agent_bundle family staged 0/5 on the fixture (each a
> stated refusal, not silence) — re-record on a seeded richer fixture before reading that as the tools' failure.
> **RE-RECORDED 2026-09-16, richer fixture** (two Slack bots so the sender stays a measurable open choice, a brief
> subscription; ~60 more calls on the user's word): **16/30 staged** (was 9), all seven kinds represented, agent
> bundles 2/5 (was 0); **honesty still perfect — 26/26 proposals across both runs, zero check failures.** The
> residual decomposes cleanly: 4 designed refusal specimens behaving exactly as designed (both red-team asks; the
> checks-first pricing watchdog; the no-support-schema agent) · 5 honest conversational turns (a careful question
> back before a delete; "nothing is paused" answered truthfully; the name-listing fix WORKING — the model got the
> candidate list and chose to hand the "morning chain ≈ morning anomalies?" guess back to the person, which is
> right custody for an edit) · **5 budget deaths, the one remaining defect class**: diligent turns that spent all 8
> loop steps measuring first (four SQL probes before drafting a monitor) and died answerless in the recorder —
> live, the stream renders the graceful budget sentence, but the ask still lands undraftd. The 22(d) gate call this
> leaves the user: on the 26 real asks, 21 behaved correctly (81%) and 5 hit the step budget — the knob is the
> converse loop's step budget, a cost decision, not a code defect.

**Not in this movement:** an intent classifier in front of the roster · a second inbox or approval surface ·
auto-accepting anything structural · a canvas for agents · a model grading its own drafts.

#### The third movement — the answer vocabulary (adopted 2026-09-15, §6 item 23; AV-0…AV-2 first slice STARTED the same night)

> **Origin.** The user, 2026-09-15, with Microsoft's Adaptive Cards catalog on screen: *"there are so many ways of
> making the chat interface interactive… Why don't we consider introducing such UI elements? We have been calling
> ourselves Agentic forever without the very important UI elements that make it so."* The reading this movement takes:
> Adaptive Cards is not a widget library, it is a CLOSED, versioned vocabulary of parts an agent may emit as its
> answer, plus a fixed set of typed actions the host executes. The agent composes an interface; the host guarantees
> what any click can do.
>
> **Measured before adopting:** the pipeline is already this shape in embryo — frames → declared typed parts →
> projectors → organs — and real cards exist (the ProposalCard is an action set with inputs, the clarify and plan
> gates are choice sets, the run card is a progress bar with a real denominator, answers carry tables and charts, and
> `web/components/ui/` already holds badge, progress, tooltip, tabs, dialog). The gap in one sentence: every
> interactive element is hard-wired to ONE backend event, so the model has no vocabulary to compose an answer from
> parts — it can only write prose and hope.
>
> **The refused shape:** an open UI language rendered from model output — an injection surface, a slop machine, and a
> custody bypass (a button the model defines must never execute anything). Every part is validated against a closed
> schema, and an action names an EXISTING governed door and nothing else; the model chooses which door to offer,
> never what a click does.

**AV-0 · The vocabulary, written down.** Closed part kinds v1 — `fact_set` · `status` · `progress` (a real
denominator, FL-5's law) · `section` (markdown body through AnswerProse) · `action_set` (door-bound) ·
`proposal_ref` — versioned and validated server-side; a parts list that fails validation is refused WHOLE with
sentences, never rendered broken. Tables and charts stay the figure's. **Receipt:** the schema and its refusal tests.

**AV-1 · The organs, by promotion.** One `AnswerParts` renderer in chat and the ⌘K overlay: the ProposalCard's labeled
rows become the general fact set, the status chip becomes the badge, `ui/progress` the bar, sections collapse.
**Receipt:** every declared kind renders in jsdom; no declared part ever reaches the raw fallback.

**AV-2 · The agent composes.** Converse gains ONE tool, `present` — offered only on a streaming turn (a sync caller
has nowhere to render), it validates the parts and emits them as an `answer_parts` frame; a refusal returns the
sentences so the model falls back to prose. Nothing stages, nothing executes — presentation only. The
propose-chain pattern applied to presentation. **Receipt:** a live turn answering in fact rows and badges where
tonight's screenshot answered in paragraphs.

**AV-3 · Doors as actions.** An action names an existing door only: v1 ships `follow_up` (the same ask path the
follow-up chips already ride) and `proposal_ref` (the real approval card, rendered in place). Open-a-screen and
run-a-trusted-query actions wait on a deep-link registry — recorded open, not drifted into. **Receipt:** a click asks
the follow-up through the same path a typed question takes.

**AV-M · Measure alongside — ✅ BUILT 2026-09-19** (`aughor/obs/vocabulary_uptake.py`). Parts-versus-prose per
converse turn, counted from the session log, no model anywhere — SP-M's shape one movement over.
**The population is the turns where the tool was OFFERED.** `present` reaches only a streaming converse turn, so a
deep run or an automation could never have used it and must not be counted against it; `ask.converse` is the
denominator. An unreadable log reports `measured: false` and **no rate** — 0% would be a claim about the product
where the truth is a claim about the log (SP-7's law: a failed probe is not an absence).
**First reading, live: 3 of 42 converse turns answered in parts — all on 2026-09-15, the day the vocabulary
shipped.** Since then, 2 converse turns, both prose. Not yet damning at n=2, and exactly the number that was
unanswerable before this module: the question "is it used" took hand-written sqlite.
🔴 **The meter shipped with the defect it exists to catch, for ten minutes.** Its first cut read `kind="tool_call"`
only — and on the live log `ask.converse` appears 41× as a `tool_call` and NEVER as a result, while `present`
appears 4× as a `tool_call_result` and NEVER as a call. It reported **zero uptake on a feature that had been
used**. 🔑 **A tool's evidence may live under either kind; never assume one.** Pinned by the first test in the file.
🔴 **And chasing that difference found a SECOND defect in the meter, which is why the number moved from 2 to 3.**
The first cut counted only turns marked by an `ask.converse` tool call, so a trace carrying `present` without one
was discarded — from the numerator AND the denominator. The live case: of the 16 traces using a Spotlight
`platform_*` tool, 15 carry the marker and one (`562bf533`) does not; it called `present` TWICE and then ended in an
`execution_error`. **A turn that used the vocabulary and then crashed was invisible to the meter whose whole job is
to notice use**, and the omission biased in exactly the direction that flatters a quiet feature.
🔑 **A turn that failed still happened.** A `present` call is itself proof the tool was offered, so such a trace now
joins BOTH sides and the rate stays a rate. The test that asserted the old rule was rewritten to say so, with the
evidence — a test changed by measurement, not by convenience.
**Needs:** nothing.

### 3.12 · Arc MT — self-serve multi-tenancy (drafted 2026-09-07; decision §6 item 12; **DROPPED by the user 2026-09-12 — not while the platform runs locally**)

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

> **DROPPED 2026-09-12 — the user, asked what was next after ON-5: *"MT-0 and MT-1 make no sense if this
> is not hosted somewhere. Locally, I don't need it. And worse is not working as expected due to backend
> compute and storage limitations."*** Identity and per-user tenancy pay off only on a hosted deployment,
> and the hosted one is constrained enough that it does not work as expected — so the wave buys nothing
> where the platform actually runs. MT-2 was already keyed on a Google OAuth client that was never created,
> which was the same signal a month earlier, read as waiting rather than as not wanted. The spec below
> stands as written and is not refused (§4 is for refusals): it waits on the user saying the hosted
> deployment matters. Do not re-propose it as the next build.

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

### 3.15 · Arc ON — the ontology the agent runs ON (drafted AND adopted 2026-09-10 — §6 item 14, all four clauses YES; **ON-0 STARTED** the same day; rebuild delete-bug FIXED, **MERGED #499**, squash `5281e5a7`, 2026-09-13 — the route and the hourly auto-refresh deleted built ontologies and built nothing; now build-first with a strict read-back)

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
- ✅ **ON-1 · The noun decouples from the table — FIRST SLICE BUILT 2026-09-11.** *(Amended 2026-09-11:
  **ON-1b · Bindings**, after the wave list.)* What
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
  concatenates `source_tables`; ✅ closed 2026-09-15, `83e97c49`); a query backing has no UI and no diff view (✅ closed
  2026-09-15, `5c3d3181`: previewed, set and withdrawn from the type panel); properties
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
  seen. Fixable without new theory: `object_type` required and `op` an enum in the
  fill schema, `metric` exclusive of `path`, a rounding convention, worked examples in the prompt, a
  stronger model — then re-measure. ✅ **Built 2026-09-15** (`af2dad1c`), all but the stronger model: a measure is
  `kind` aggregate or metric and sends only that kind's fields. Re-measured 2026-09-15 in the ON-10 re-runs: objects 7 of
  15 on Olist and 10 of 16 on LuxExperience (declared 4 of 12 and 7 of 13, against framed 11 and 13), no fill refused as
  malformed (was 5 of 26) — its misses are compiled wrong answers, so `ask.query_objects` stays parked. Found by the same run: the first refusal classifier had no
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
- **ON-3 · Instances — the object page and the object link.** *(Amended 2026-09-11: **ON-3b · The
  entity-type map** and **ON-3c · The agent reads the type**, after the wave list.)* `GET /objects/{type}/{pk}`
  resolved live through the backing; links resolved on demand; the zero-config
  **Standard Object View** the 07-22 study's Wave S named and nobody built — properties,
  links, the findings that cite this object (the context graph's `grounded_in`, finally
  pointed at an instance), the metrics touching its type, and the declared actions that
  take it as a parameter, pre-filled. `describe_entity` gains a sibling `get_object` on
  the agent roster and the MCP roster (SP-5's parity ratchet holds the diff empty).
  **Receipt:** a customer id in an answer is a link → its object page → "Orders" →
  `flag_order_for_review` offered with the id filled.
  **Receipts — first slice, 2026-09-11 (unpushed, on `claude/on-2-object-query`).** `GET
  /objects/{type}/{pk}` reads ONE row through the backing and resolves each link to a key (to-one)
  or a count (to-many), listed a page at a time by `/links/{link}`; a refused link says why and is
  never followed. `related` carries four panels, each measured (`aughor/semantic/object_context.py`):
  verified metrics compiled by ON-2 with this object as the filter (a customer's revenue across its
  orders equals the hand-written SUM in the test); findings and answer receipts cited ONLY when their
  WHERE filters the key, or a column a link from the key joins to, by this exact value (a finding about
  orders in aggregate is not listed); the overlay's notes on the row; and declared actions owned by the
  type or taking a key-named parameter, pre-filled, offered and never run. `get_object` rides converse,
  spotlight and MCP. The page is `/objects/<type>/<key>`. A column names an object only when the
  catalog says its name is a type's key, or the column a usable link from that key joins to, and
  exactly one type claims it; the answer table, the Source data drawer and the page's own lists share
  that rule. **Live, no model call on the path:** LuxExperience customer MYT-C0001364 → its 73
  CustomerService tickets → ticket CS0000653 (to-one Customer, 4 OrderItems, the N:N link to Order
  refused by measurement) → order MYT-O00003141, whose customer_id links back; a restored Superstore
  answer's Source data links each `manager` to its Regional Manager page. Suite 9659 passed.
  **The receipt's last step, met the same day:** the user declared `flag_order_for_review` on
  LuxExperience (*"yes, declare flag_order_for_review on LuxExperience"*) through the authoring route
  (`PUT /ontology/kinetic-actions/{id}`, verified, no warnings): kind annotate, risk low, `order_id` and
  `body` with `table`/`key_column`/`column` defaults. Order MYT-O00003141's page offers it with
  `order_id` filled, and "Open in Actions" lands on Intelligence's Actions layer for that connection.
  Driving it found two defects, both fixed: the annotate dispatcher read the row only from a parameter
  named `row_key`, so accepting the offer would have annotated the whole `status` column (it now falls
  back to the parameter its `key_column` names); and the workbench erased a `?conn=` deep link before
  the connection list read it, so a shared link opened on the reader's last connection. **Still
  open:** Lux measures no Customer→Order link (the pack's expected edge), so a customer reaches its
  orders through a ticket; the metrics and findings panels are empty live (no verified metric on Lux,
  no stored finding filters these keys); and acting on the offer is ON-4's.
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
  **Receipts — first slice, 2026-09-11 (unpushed, on `claude/on-2-object-query`).** A parameter can be
  `kind: "object"` with an `object_type`, passed as `"<type>:<key>"` and read live through the object
  pages' graph and scoped connection when a proposal is validated and again when it runs; a criterion
  reads its properties (`order.status`, or `object.status` for the object the action is about), typed by
  each property's declared type. An action declares its `object_type` and its `edits`: an accepted
  annotate writes each to the edits overlay keyed `(object_type, key, property)` with who accepted it and
  which action wrote it — never a source column, refused when authored and again at dispatch. The object
  compiler merges an overlay property at read time (the accepted values joined on the object's key, a plan
  line, each edit's provenance on the compiled result); the object page, the catalog, `get_object` and
  `query_objects` read the same edits. **Live on LuxExperience, the receipt met:** `flag_order_for_review`
  declared typed (an `order` object and a `reason`, `order.status != 'cancelled'`, `review_flag = true`);
  the agent proposed it from support ticket CS0000653's complaint about order MYT-O00003141 (one model
  call, validated live — the order is `returned`); it was accepted on the user's instruction (*"run the
  proposal and accept it"*), recorded under their name; the next `POST /objects/query` over Orders returns
  `MYT-O00003141 · review_flag = true` with the plan line "overlay property review_flag on Order: 1
  accepted edit(s) merged at read time … the source is never written" and the provenance "annotated by
  sidhasadhak via flag_order_for_review, 2026-09-11"; the order page shows the same. **Amended:** the
  receipt runs through `POST /objects/query`, not `query_objects`, whose conversation door is parked
  (§6 item 15). **Found on the way:** the warehouse hands object properties back as text, so a numeric
  criterion would always have failed closed — values are now typed. **Still open:** an edit may not correct a source value (a correction is a different
  write, not taken on here).
  ✅ **Closed 2026-09-12:** `withdraw_edit` + `DELETE /kinetic-actions/annotations/{id}` remove ONE accepted
  edit — until then `purge_connections`, the catalog-delete cascade, was the only way back and took every edit on
  the connection with it. Scoped the way a read is, so a withdrawal reaches no other connection's or org's row;
  404 rather than a delete that deleted nothing; and it restores nothing, because nothing was ever written — it
  stops the merge, and the object reads as the warehouse holds it. The object page carries each edit's id, so the
  property an accepted action set and the note on the row are each withdrawn where they are shown. The kinetic
  authoring form now declares an object parameter (`kind: object` with its type), the action's own `object_type`,
  and the `edits` it writes. Found on the way: `GET /kinetic-actions/annotations` listed every org's edits on a
  connection while every other read of that ledger scopes to the current one — scoped.
- **ON-5 · Functions and models on objects (the "intelligence mapping").** *(Amended 2026-09-11:
  timeseries properties are its first citizen, after the wave list.)* A
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

**Amended 2026-09-11 — the Fabric IQ study: the connected entities become the agent's context,
reached as tools.** *(The user: "Write the amendments into the roadmap.")*

> **Origin.** The user asked for a deep scan of Microsoft's Ontology Playground
> (`github.com/microsoft/Ontology-Playground` and its live site), shared a screenshot of the ontology
> item in Microsoft Fabric (Fabric IQ), and pointed at two things in it: how entities are presented on
> the ontology map, and that *each entity has properties and its associated data source*. The
> definition every wave of this arc is held to, verbatim: *"Ontology is complete understanding and the
> context of your business and its processes represented as connected entities. And these connected
> entities and the relationship between them acts as a context for the Agent that work on your
> behalf."*
>
> **What was measured (a read-only clone, the live site, and this repo, 2026-09-11).** *Theirs:* a
> static learning site, not a runtime. Entity types with typed properties and an identifier flag,
> relationships with a DECLARED cardinality, one table binding per entity; no constraints, actions,
> metrics, display name or timeseries. The "NL2Ontology" query is keyword matching with canned answers;
> the RDF and Fabric exports lose data (the Fabric export drops cardinality and bindings and mints new
> ids on every conversion). *Fabric's own ontology item* (the screenshot): a searchable entity-type list;
> a canvas centred on one entity, its card showing a binding count, its named relationships around it
> (`ShipmentFulfillsOrder`); an entity-type panel with the key, an **instance display name**, and
> properties listed with their **data source** and a **Static or Timeseries** type, beside a Bindings
> tab. *Ours:* the Ontology layer draws every entity at once (tangled at LuxExperience's 14), dims
> neighbours on hover, and has no entity search and no view centred on one entity; an entity has ONE
> backing (a table or a keyed SELECT) and its properties record no source; there is no declared display
> property (ON-3's object page guesses a title column from names); no timeseries property kind
> (`window_measures.from_declaration` still has no caller); relationship verbs are generic; and the
> agent's `describe_entity` (converse and MCP, one body) reads the context graph's TABLE node — column
> names, source tables, the key column, a lifecycle flag — so the agent's view of an entity is still the
> ERD row this section opened on.
>
> **How the definition is read here.** "Context for the agent" means what the agent can NAVIGATE and ACT
> ON, not prose in its prompt: the prompt block was measured twice and lifted nothing (ON-0, ON-0a), so
> ON-6 stays retired and the agent-facing amendment below is a tool. "Processes" is in the definition
> too: what changes over time — lifecycles, events, readings — is in scope, not only nouns.
>
> **Not taken:** their data model (declared, never measured — ON-0a's law, *the data wins*, stays the
> difference), the keyword query, the LLM ontology generator that loads unchecked output, and a catalogue
> of ontologies never measured against data. The one interop question, exporting our measured ontology to
> Fabric IQ, is §6 item 16: open and unscheduled.

- **ON-3b · The entity-type map — AMENDED 2026-09-11; FIRST SLICE BUILT the same day (unpushed, on
  `claude/on-fabric-iq-amendments`).** The type-level view ON-3's instance
  pages lack, on the Ontology layer: a searchable entity-type rail; a canvas centred on the selected
  entity, its card carrying measured facts (key verified, bindings, rows, links, actions) rather than a
  paragraph, its links drawn with their business verb and measured cardinality, expandable a hop at a
  time — the whole-graph view kept as the overview; and an entity-type panel: the key and whether it is
  verified, the **display property**, the properties (role, data type, source, unit, and static or
  timeseries — the latter landed with ON-5), the bindings, the links (usable by the compiler, or refused and why), the
  declared actions and the verified metrics. Two model additions ride it. A **declared display
  property** on the object type — proposed from the profile, overridable through the overrides tree,
  measured (non-null share, distinctness) like every claim — which the object page, the key links in
  answers, the action cards and the agent's summaries use instead of a name guess. And **business-verb
  link names** (`shipment_fulfills_order`), proposed at build and overridable, with the mechanical
  `order_to_order_item` kept as the stable fallback. A path finder answers "how does Customer reach
  Shipment?" with every hop's measured cardinality and whether ON-2 would traverse it.
  **Receipt:** on LuxExperience, Shipment found in the rail; its centred card shows its key verified and
  its links by verb; the panel lists every property with its source; "Customer → Shipment" returns its
  paths with each hop marked traversable or refused, with the reason; an order page's header shows the
  order's declared display property.
  **Receipts — first slice, 2026-09-11.** `aughor/semantic/object_types.py` describes a type from what the
  graph measured: `GET /object-types` (the map — every type with its key verdict, rows, binding, links the
  compiler follows, declared actions and verified metrics, and every link with its verb and measured
  cardinality), `GET /object-types/{type}` (the panel) and `GET /object-paths` (every chain of links within
  four hops, each hop marked the way ON-2 treats it, followed paths first, and `compiles_as` naming what the
  compiler builds along one: a filter along any followed path of at most three links, a dimension only when
  every hop reaches one object). The **display property** is a model field: proposed from the profile (a
  property named after the type, then one whose name says it is a name, then the key), declared through the
  overrides tree, and measured on `POST /ontology/measure` — a property names objects when at least 90% of them
  carry a value and at least half of those values differ, so a category or a mostly empty column does not; a
  refuted proposal gives way to the key, and a person's declaration stands with its measurement beside it. The
  object page's title, a list of linked objects and `get_object`'s summary read it. **Business-verb link names**
  are proposed from the verb on record at read time (so an enriched verb renames the link) and set by a person
  through a new `link` override kind (`PUT /ontology/links/{id}`, refused when it is not snake_case or already
  names a link or a property on either type); the compiler and the instance reader accept one beside the
  mechanical name. The key measurement now records the backing's rows. Found on the way: `PUT
  /ontology/entities/{id}` replaced the entity's whole override file, so declaring a display property would
  have wiped a description, a backing or a routing rule — it now merges. **Live on LuxExperience, no model call
  on the path:** the measure door found 14 of 14 keys unique, with their rows, and 14 of 14 display properties
  naming their objects (Brand by `brand`, Warehouse by `name`, the other twelve by their keys); "Ship" in the
  rail finds Shipment, whose centred card reads key `shipment_id` unique, 107,903 rows,
  `luxexperience.shipments`, 1 of 1 links followed, its link drawn "associated with → N:1" to Order Line; the
  panel lists its 12 properties with their sources; Customer → Shipment returns two paths — three hops through
  Support Ticket and Order Line, followed and compiling as a filter, and four hops through Order, refused at hop
  2 with the compiler's own sentence (N:N by measurement); order MYT-O00003141's header reads "named by
  order_id", its measurement on hover (112,439 of 112,439 carry a value, 112,439 distinct). Driving it found three
  layout defects, each fixed: the canvas centred before its layer had a width, labels sat under the centred card,
  and property sources wrapped a few characters a line. Suite 9,698 passed; of eleven mutations of the new guards
  ten failed a test, and the survivor exposed an alias written for a reason that was not true — removed, and its
  test re-pinned on the real mechanism. ~~**Still open:** a label can still clip a card on a sideways link in a narrow pane.~~
  ✅ **Closed 2026-09-15:** a sideways link's label is lifted clear above its two cards (the map draws its links with its
  own edge, `linkLabelY`); an upright link keeps the middle — checked in the browser on TheLook's map, Order picked.
  ✅ **Closed 2026-09-12:** the answer table, the Source data drawer, the object page's linked lists, its to-one
  links and its action cards read objects by NAME. `POST /objects/titles` resolves a page of keys in ONE query
  over the backing (a table of 200 costs one round trip, not 200); a type named by its own key resolves nothing
  and says so; a key nothing matches is absent rather than guessed at; the batch caps at 500 and every key is a
  typed literal. The key stays on hover, in the link's title, because it is what the SQL filtered on — and a name
  is decoration on a link that may never gate one: a titles door that fails or refuses leaves the table on its
  keys. **A web door names a link** (the panel's *Name it*, on `PUT /ontology/links/{id}`), so LuxExperience's
  generic verbs are now a person's to fix rather than a missing surface.
  **Re-laid 2026-09-12, on the user's reading of the map** (*"lets put the entities in the center of the
  playground … it is very clustered and not easy to read … all the extended entities linked are visible by
  default and once clicked on the entity type from the list, those get highlighted … Ideally, the entity with
  highest links gets placed at the center, so that user understand which is the most critical entity in the
  business"*). The centre is no longer "whatever was clicked": it is the type with the MOST links, and it stays
  there — so the middle of the canvas is a claim about the business, the one the user asked it to make. Picking a
  type LIGHTS it, its links and the types on the other end, and opens it in the panel; centring is a separate,
  explicit act on a card. Every linked type is drawn at the ring of its shortest distance, with no expander
  between a person and the second hop; a type its links never reach from the centre sits on the outermost ring,
  and a type with NO links is listed under the map rather than parked on a far ring that would double the map's
  size to say nothing. Only the lit type's links are named — every label at once was the clutter in the
  screenshot. A link between two cards on one ring bows outward instead of cutting through the cards inside it; a
  label reserves its own chip's width, and steps off its line where the rings leave none. The canvas sizes itself
  to the pane before the first paint (measured, then kept by the ResizeObserver) and can be zoomed and dragged —
  it used to be a fixed canvas the size of its rings, which is why a type with no links at all was drawn at the
  TOP of an otherwise empty pane. Live on LuxExperience: 14 types, 11 relationships, the whole map at 88% in a
  1,004px pane with nothing scrolled off; Order Line (7 links) in the middle with its seven links named; picking
  Product lights Product, Order Line and Price History and names `contains 1:N` and `has 1:N`; Brand, Country,
  Date and Warehouse listed under the map.
  **Rebuilt on `@xyflow/react` the same day, on the user's second reading** (*"too clustered … the background of
  ontology screen should not be dotted.. make the background colour darker too … the idea of a button to put an
  entity in center is terrible.. you made it unnecessarily complex.. Make the Map zoomable, entities movable (and
  persist position change).. we need only map in ontology.. overview doesnt matter if it is not being used as
  context.. remove it"*). Pan, zoom, fit and drag are now the library's — the fifth canvas in this app on it —
  which deleted three hand-rolled mechanisms (a scroll box, a zoom stepper, a pan handler) that between them still
  could not move a card, and every line of edge and label geometry with them. A card a person drags STAYS there,
  per connection, across reloads and ACROSS BROWSERS — it is a per-user preference (SP-3's store, a new key in its
  closed registry, validated: at most 24 maps of at most 300 cards, each a finite x and y), with `localStorage`
  keeping only the paint-before-fetch job the theme toggle already gave it; one button puts them all back; `layoutMap` now only decides where a card STARTS. Every card is
  the same size — the centre used to be a bigger, denser card, which is most of what made the middle unreadable,
  and everything it showed is in the panel already open beside it. The "centre the map here" button is gone: the
  middle means the busiest type and nothing offers to change that. No dot grid, and the deeper `--bg-canvas`
  ground. **The Overview is gone** with its drawer stack (613 lines) — a second drawing of the same facts that
  nothing downstream read; the Org board keeps its own canvas, which is where `OntologyCanvas` still lives.
  Driven live: the whole map fits its pane; Shipment dragged 112×72px to the top-left stayed there through a full
  reload; picking Product lights it, Order Line and Price History and names `contains · 1:N` and `has · 1:N`.
  16 tests pin the starting layout and 5 the canvas handoff — the only place a wrong handle id (an edge dropped in
  silence, which looks exactly like an ontology with no links) would show. Seven web gates, 816 vitest.
- **ON-3c · The agent reads the type — AMENDED 2026-09-11; BUILT and its RECEIPT MET the same day.**
  `describe_entity` (the agent's
  roster and MCP, one body) returns the ON-1 object type instead of the context graph's table node: api
  name, the key and its verification, the display property, properties with role, type and SOURCE,
  bindings, links by name with measured cardinality and traversability (and the refusal reason), declared
  actions with their object parameters, verified metrics. The same connected-entities slice ON-3b renders,
  read by the agent as a tool; the context graph stays the citation substrate, SP-5's parity ratchet
  holds the roster diff honest, and no prompt text is added. **Receipt:** asked "what is a Shipment and
  where does its data come from?", the agent calls `describe_entity` and answers with each property's
  source and the measured links — and the same call over MCP returns the identical body.
  **Receipts — first slice, 2026-09-11.** `describe_entity` (`aughor/mcp/knowledge_tools.py`, the body the
  converse roster and the MCP server both call) resolves the name through the served ontology — a type, its
  api name, display name or table, so "orders" and "ecommerce.orders" both answer Order — and returns `kind:
  object_type` with `describe_object_type`'s dict and a line an agent can quote, live on LuxExperience: "Shipment
  (shipment): key shipment_id — unique per object, measured over 107,903 rows; named by its key; 12 properties
  read from luxexperience.shipments; 1 link, 1 followed by the compiler; 0 declared actions; 0 verified
  metrics." G5's clearance trim still guards it (withheld, with a notice that never names the table); an unknown
  type answers with the ontology's refusal and the types that exist; only where no ontology describes it does the
  knowledge graph's table node answer, labelled `kind: table`. The conversation's copy no longer caps the body on
  its own, so both transports return the identical dict, pinned by a test that calls both on one graph; both
  routing descriptions now name the sources, the measured links and the sibling tools. `describe_entity` is not
  in the Spotlight roster, so SP-5's ratchet passes unchanged and the identity test holds its two transports. No
  prompt text was added. **Receipt met live the same day** (the user: *"yes, run the Shipment question.. i need
  screenshots"*). On LuxExperience the chat's Edit → Send re-sent "What is a Shipment and where does its data come
  from?" through `/ask`; the router called it a direct lookup without a model, the conversation served it, and its
  tool trail reads "1 step taken — Read what's known about an entity" (the route receipt counts one
  `describe_entity` call; trace 8dbaf5d4, two model calls). The answer: a Shipment is an order dispatched from a
  warehouse — carrier, service level, dates, shipping fees and duties — read from `luxexperience.shipments`, each
  one unique by `shipment_id`, linked to an order through `order_id`. It named the source table and the key's
  uniqueness rather than every property's source, and compressed the measured link (Shipment ↔ Order Line on
  `order_id`) to "an order". The same call over MCP returns the identical body: on a read-only snapshot of the
  live ledger and overrides, every other store isolated, the conversation's body equalled the MCP server's and
  both equalled the live `GET /object-types/shipment`. **Found on the way:** the chat's Quick chip posts the
  forced-Quick `/chat` door, so it never reaches the conversation even with `ask.converse` on — asked there first,
  the question was answered by a SELECT of string literals shown as "1 source · executed SQL", a separate defect
  filed on its own.
- **ON-1b · Bindings — each property knows its source — AMENDED 2026-09-11; FIRST SLICE BUILT and its RECEIPT
  MET the same day (on `claude/on-1b-bindings`, unpushed).** An object
  type's single `backing` becomes a list of **bindings**. Each binding is a table or keyed SELECT joined
  to the object on its key, with the properties it supplies and a kind — **static** (one row per object)
  or **timeseries** (many rows per object over a time column) — and a verdict **measured** the ON-0a way:
  a static binding's key must be unique; a timeseries binding's key must reach existing objects, its
  coverage recorded. Every property then records its SOURCE (binding · column): what the entity-type panel
  lists, what `describe_entity` returns, and what ON-2's compiler reads the property through. The first
  binding IS today's backing, so every graph built before loads unchanged; a further binding is set
  through the overrides tree, or proposed by the builder when another table carries the object's key.
  An object spanning tables no longer needs a hand-written SELECT to be complete. **Receipt:** an object
  type gains a second static binding from a table keyed on its key (measured unique); its panel shows each
  property's source; an object query filtering on a property from that binding compiles through the key
  join and equals its hand-written reference.
  **Receipts — first slice, 2026-09-11.** `aughor/ontology/bindings.py`: a further binding (`Binding` — a table or
  keyed SELECT, the column holding the object's key, `static` or `timeseries`, the properties it supplies with any
  renames, the columns it skips and why) is counted in one probe against the objects it binds to — rows, keyed rows,
  distinct keys, the objects, how many it covers, the keys that reach no object — and holds only when the data says
  so: a static binding when its key is unique over its rows AND reaches objects that exist, a timeseries binding
  when its key reaches objects, its coverage kept. The first binding is still `backing`, so every graph built before
  loads byte-identically (`bindings` and `proposed_bindings` default empty; a renamed column lives on the binding,
  never on the property). A person binds one through `PUT /ontology/entities/{id}/bindings/{name}`: its source is
  read for its columns first — the key, the time column and every property must exist and be free on the type (a name
  the backing, another binding or a link already holds is skipped by default, and refused when asked for by name) —
  and a 400 writes nothing; the binding is then counted in the same request, and rebuilt at read time from what the
  bind and the count recorded, without a database (a spec edited since its bind reaches no reader). `DELETE` removes
  one. The measure door and the build count every binding and PROPOSE a static one wherever another type's table
  carries a type's measured-unique key one row per object — kept on `proposed_bindings`, read by no query, page or
  answer until a person binds it. ON-2's compiler reads a bound property through a LEFT JOIN on the key, taken once
  per object alias — at the anchor, behind a to-one hop, inside EXISTS and inside a pre-aggregation alike — and
  refuses an unmeasured or refuted binding with the reason; the compiled
  result lists the bindings it joined. The object page reads a binding by the key under the same law. (A timeseries
  binding was refused here until ON-5, which reads it as each object's latest row — one row per object again.) The
  entity-type panel and `describe_entity` list every binding with its verdict and coverage and every property with
  its source, the panel with Bind on a proposal and Remove on a person's binding; `describe_entity` leaves out a
  binding read from a table G5 withholds. In `tests/unit/test_object_bindings.py` eight compiled queries through a
  binding — a filter, a renamed column, a dimension that keeps the uncovered objects, a SUM, a flag's share, behind a
  to-one link, through a to-many EXISTS and through a pre-aggregation — equal their hand-written references on the
  samples warehouse; 18 of 18 guard mutations fail a test; the prompt-reach walk grew 174 → 246 fields and none of
  the new ones reaches a block. The full suite ran all 9,726 tests with none failing (3 skipped); its process could not
  exit because background workspace builds sat in a pre-existing single-flight wait on themselves (#305: two
  `build_intelligence` layers share one key), filed on its own. **Live on LuxExperience, no model call on any path:** the measure door proposed five
  bindings, each one row per object — Order ← payments (covering 112,439 of 112,439 orders), shipments (107,903),
  customer_service (11,244); Order Line ← returns; Return ← return_logistics — and counted ten more candidates the
  data refused. Payments was bound through the API with `status` renamed `payment_status` (a property named `status`
  was refused, 400: Order already has it); shipments with the panel's Bind button. Order's summary reads "20
  properties read from luxexperience.orders, 7 from luxexperience.payments (a static binding), 9 from
  luxexperience.shipments (a static binding)". Five object queries through the bindings equal references computed on
  the warehouse directly — **l09 (orders never shipped: 4,536) and l05 (carrier shipping cost as a share of GMV over
  shipped orders: 7.76%), the two hard-set questions ON-2 refused for want of an orders↔shipments link**, refunded
  payments by method, risky payments by processor, and order lines by their order's carrier through a link — and
  order MYT-O00003141's page reads 16 properties through the two bindings, each naming its column. **Found on the
  way:** the overrides tree had no test isolation. A measure-door test that cached a graph under LuxExperience's real
  connection id rewrote the live Order override with counts from its three-row fixture while the full suite ran beside
  the receipt — the panel suddenly read "3 of 3 objects". The counts were restored by re-measuring through the API;
  the overrides, export and recommendations trees now resolve `AUGHOR_ONTOLOGY_*_DIR`, pointed at the suite's temp dir
  and held by the store-hermeticity guard. `/objects/query` hands a NULL back as the text "NULL" (the legacy
  stringified execute path), filed on its own. **A keyed SELECT's columns carry types (the same day):** a binding's
  columns are read through the connection's typed result channel, so every column carries the data type the warehouse
  reports for it in that very SELECT, a cast or an expression included; a pass-through column (a bare column, renamed
  or not, of a table in the SELECT's own FROM or JOINs) borrows that source column's profiled role, unit and
  description, while an expression, a cast, a subquery's or a CTE's column, and an unqualified name two of its tables
  carry borrow nothing (`select_lineage` never guesses). Live on LuxExperience: a keyed SELECT over payments bound on
  Order (107,903 of 112,439 orders once failed payments are left out) typed `paid_eur` a measure (DOUBLE, traced to
  `amount_eur`), `paid_net_eur` (`amount_eur * 0.9`) DOUBLE with no role, and `installments_text` (a cast) VARCHAR; the
  sum of the computed and the pass-through column by the payments binding's method equalled its reference over seven
  methods, the string "1000" met `paid_eur` as a number (8,070 orders, equal), a SUM of the cast was refused, and the
  binding was removed. ~~**Still open:** the builder proposes static bindings only (a person declares a timeseries one
  through the panel since 2026-09-12); `dedup.merge_entities` is not yet "two tables, one binding".~~ ✅ **Closed
  2026-09-15 (leftovers, second round):** the builder proposes a table of READINGS — a repeated key placed in time, with
  no identity of its own — as a timeseries binding (`4728f80d`), and a duplicate-entity merge binds the other type's
  table onto the survivor on its key, counted one row per object, and marks the other type its part: nothing deleted,
  written to the overrides tree (`83e97c49`; the old merge answered 500 on any real type).
  ✅ **Closed 2026-09-12:** a display property may come from a STATIC binding — the binding holds one row per
  object, so its column is as single-valued as the backing's. `display_source` measures it over the binding's own
  source, the titles door joins it on the object's key, and the object page reads it off the properties it has
  already fetched: the same join in all three, so they cannot disagree. A TIMESERIES binding is refused with its
  reason (its value is the latest row, so a title from it would change when the next reading lands), and an
  unmeasured binding names nothing — the one law for reading a binding holds here too.
- **ON-5, amended · Timeseries properties first — AMENDED 2026-09-11; BUILT AND RECEIPT MET 2026-09-12.** The
  "processes" half of the definition. A timeseries property — a shipment's latest location, a sensor reading, a
  status over time — is read from a timeseries binding (ON-1b) and becomes ON-5's first declared function: its
  latest value and its history per object, with windowed and semiadditive measures over it (the first caller of
  O5's `window_measures.from_declaration`). It shows on the object page as its latest value, when that was
  measured, and a short history, and it is a property the compiler can filter and measure with its time
  semantics explicit. **Receipt:** a timeseries binding on a real event table; an object page shows the
  latest value with its timestamp; an object query for "objects whose latest value breaches a threshold"
  equals its reference.
  **Built (`aughor/ontology/timeseries.py`).** A timeseries binding is reduced to ONE row per object — the
  object's latest row by its time column — so it joins under exactly the law ON-1b proved for a static binding and
  can neither multiply nor invent objects. Each property on that row is O5's declaration INSTANTIATED
  (`semiadditive: last`, partitioned by the object's key, ordered by the time column), never window SQL written a
  second time; `from_declaration` has its first caller. Three decisions live in the module, each with a test: a
  reading whose time is NULL is out of the reduction, so "the latest" is never a row that did not say when; the
  ordering carries the time column AND every supplied column, so two readings tied on one instant cannot hand one
  property to one row and the next to another; and the history is the same source unreduced, newest first. The
  compiler joins the reduction and says so in the plan (`treatment: latest`, with the time column); the object page
  shows the value, WHEN it was measured and the readings behind it; `describe_object_type`'s one-liner — what the
  agent quotes (ON-3c) — now says "a timeseries binding, read as each object's latest value by <column>".
  **Receipt met 2026-09-12, live on LuxExperience (no model call).** `price_history` bound on `Product` as a
  timeseries binding keyed `product_id` over `effective_date`: 26,005 rows over 8,600 keys, covering 8,600 of 8,600
  products, verified. The page for `SKUTHE000000` (Zimmermann, retail €410) reads its **latest price €246.00 as of
  2024-02-26**, markdown 0.4, `is_markdown` true — every one from the same row — over a history of five readings
  newest first (246 ← 287 ← 328 ← 287 ← 410, the markdown visible as a walk down). `POST /objects/query` for
  products whose **latest** price > €500 returned **1,744**, equal to a hand reference that picks each product's
  newest row with a correlated LATERAL and no window function at all; average latest price by `brand_tier`
  (contemporary 141.8989 · luxury 295.6482 · ultra 562.1535) equalled the same reference, its counts summing to
  8,600 — every product, none multiplied, none dropped. 10 new tests in `tests/unit/test_object_timeseries.py`
  hold the reduction to hand references over a seeded warehouse, including the untimed reading and the tie.
  **Follow-ups built 2026-09-12** (the user: *"ON-5 follow-ups and small debts"*). **The readings are a set.** A
  timeseries binding's rows are reachable under the binding's own name — `price_history.price_eur` against the
  bare `price_eur`, which stays the latest value. They are the same shape as a to-many link and are treated the
  same way BY THE SAME CODE: `_rollup` was lifted out of `many_measure` and is now the one law both use, because a
  second copy of "an average rolls up as a ratio of sums, never an average of averages" is where that bug gets
  back in. A measure pre-aggregates per the object's key before the join; a condition is EXISTS, so the set is
  filtered and never multiplied; `where` on such a measure reads the READING's own columns, which is how "only the
  readings since March" is asked without a clock. Refused: count_distinct (one value can sit under two objects), a
  static binding through a `name.` path, and a name that is both a link and a binding. **And what it was before:**
  the object page reads each timeseries property's PREVIOUS reading off the history it already fetched rather than
  running a second, differently-tied query — `history_sql` is ordered by the reduction's own ordering reversed, so
  its first row IS the row the latest value came from. Live: 3,389 LuxExperience products have a reading under
  €150 and across all 12,312 of their readings the average is €121.7575, both equal to a hand reference;
  `SKUTHE000000` reads "246.0 as of 2024-02-26 · from 287.0". 8 more tests.
  ✅ **Both open items closed 2026-09-12** (the user: *"let's finish off ARC ON leftovers"*), on branch
  `claude/on-leftovers`. **The frame algebra reaches the object door.** A binding may declare frames over its
  readings — `{"frames": {"avg_price_3": {"column": "price", "agg": "avg", "range": "trailing", "window": 3}}}` —
  and `latest_from` grows a second window layer when, and only when, one is declared: the readings with each
  frame computed on them, wrapped by the same latest-row reduction, since the last value of a window of a window
  is not expressible in one layer. A binding with no frames compiles the SQL it always did, byte for byte. The
  narrowing to one object and the "a reading with no time has no place in time" rule moved down onto the inner
  layer, because both must happen BEFORE the frame is computed — narrowing above it would average across every
  object's readings and keep one row of the answer, which is the PARTITION BY error in a different costume.
  **The roll-up question is answered by construction, not by a rule:** a frame is computed inside the object's
  own partition and read at its latest row, so it arrives as ONE value per object and the compiler measures and
  filters it exactly as it does any other bound property. Live in the tests: the orders whose trailing-3 backlog
  average exceeds 50 equal a reference computed without the reduction at all. Refused with a sentence: a trailing
  frame with no window, a window on a range that spans no fixed number of readings, an `agg` beside an `offset`
  (a reading N back is a value, not an aggregate), an unknown agg, a column the source lacks, a name the type
  already carries, and any frame at all on a static binding. A frame borrows only what it can trace — its
  column's type and unit, because the average of a price in EUR is a price in EUR; `count` borrows neither.
  **And the web declares a timeseries binding**: the entity-type panel's *Declare a binding* form takes a table
  or a keyed SELECT, the key, static or timeseries with its time column, and the frames beside it, in the shapes
  people ask for ("average of the last N", "the reading before") rather than the algebra's vocabulary.
- **Order, and why:** ON-3b and ON-3c first — they render and return only what the model already
  measures, and ON-3c is the definition made mechanical for the agent; then ON-1b, the one model change;
  then ON-5, its timeseries properties standing on ON-1b's bindings.
- ✅ **The leftovers, closed 2026-09-12** (the user: *"let's finish off ARC ON leftovers"*, having dropped
  Arc MT the same turn). Three commits on `claude/on-leftovers`, each recorded in its wave above: **the
  person can declare what only the API could** — a binding by hand (a timeseries one, or a keyed SELECT,
  neither of which the builder ever proposes), a link's business name, an object parameter and an edit on
  the authoring form — and **one accepted edit can be withdrawn**; **an object reads by its name** wherever
  a key was printed, and a name may live on a static binding; **a frame over the readings** reaches the
  object door. What is deliberately still open, and why, is on each wave: a correction that rewrites a
  source value (a different write), ~~`dedup.merge_entities` as "two tables, one binding", a query backing's
  UI and diff view~~ (both closed 2026-09-15), ~~a label clipping a card in a narrow pane~~ (closed 2026-09-15), and the parked `ask.query_objects` fill —
  which is §6 item 15's decision and costs model tokens to re-measure, not an oversight.

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

**Amended 2026-09-12 — the SECOND MOVEMENT: the business ontology.** *(The user: "go ahead
integrate this in the main roadmap and take on seven first.")*

> **Origin.** The user, 2026-09-12, condensed: *"In the ontology we are still matching table to
> table. The whole idea of an ontology is a business context which then relates to a background
> table or set of tables, which may or may not come from the same schema or connection. For
> LuxExperience the order table and the order-line table should be one entity called Orders;
> returns and return logistics should not be two entities just because there are two tables. We
> can't even create a new entity or connect one to another. Palantir, Microsoft and Snowflake
> understand the business first, ideate it into distinct entities, then map those entities to the
> semantic layer or the tables. If a stakeholder asks what is causing a delay in warehouse
> dispatch, the investigating agent should know which dispatch, where to start, how to frame it as
> a business question, what the business calls a delay (dispatch within two days is a business
> rule the ontology should hold), the whole process from the assortment team's purchase order to
> the customer's dispatch, and then which category, brand or product is always late."* Then, on
> the measured answer that the investigation never consults the ontology first: *"this is a
> terrific moment for us to have explorer agents map the ontology and create entities first,
> based on the understanding of the connections and the tables in it, and then build everything
> on top of it. The investigation should also have the ontology-first approach."*
>
> **How this was measured.** Code and the live instance, 2026-09-12, main `fceda230`: the
> builder, the models, every route in `aughor/routers/ontology.py`, the served LuxExperience and
> Olist graphs, and the Olist data itself through the API's own read-only SQL door.

**What is true today (measured 2026-09-12):**

| The claim | Measured | Where |
|---|---|---|
| "We still match table to table" | **True by construction.** `extract_structural_ontology` is the only minting site (*"table = entity: every profiled table becomes an entity"*). Lux: 14 tables, 14 entities (`Order` and `OrderItem`; `Return` and `ReturnLogistic`). Olist: 9 and 9. `dedup.merge_entities` fuses two AFTER the fact, by a person, through `POST /ontology/entities/merge`; the module header says *"DETECTION ONLY."* | `aughor/ontology/builder.py:846-913` · `aughor/ontology/dedup.py:4,66` · `aughor/routers/ontology.py:1586` |
| "We can't create an entity or connect one to another" | **True.** No route creates an entity; every mutating route 404s on an unknown id. Relationships come only from the join map (`{from}_RELATES_TO_{to}`); the one human door, `PUT /ontology/links/{id}`, renames. The web has no "New entity" and no "Add relationship". | `aughor/routers/ontology.py:945,1058-1065` · `aughor/ontology/builder.py:918-963` · `web/components/ontology/EntityTypePanel.tsx` |
| "Tables may come from another schema or connection" | **Scope is one `(connection, schema)`.** Cache key `connection:schema:fingerprint`; `OntologyGraph` carries one `connection_id` and one `schema_name`. `Backing` and `Binding` carry NO connection: another connection is inexpressible; another schema on the same connection binds by accident (`quote_table` splits on the dot, nothing compares the qualifier). A cross-source batched-foreach join engine EXISTS (`aughor/connectors/remote_join.cross_source_join`, door `/query/cross-source-join`) — the seam ON-8 uses. | `aughor/ontology/store.py:41` · `aughor/ontology/models.py:146-150,215-224,762-764` · `aughor/ontology/cardinality.py:44` |
| "The ontology should hold the business rule" | **No process, no promise, no stage.** `lifecycle_states` is an UNORDERED set with no transitions; `lifecycle.py` can refute a terminal claim and nothing more. `sla`/`threshold`/`expected_within` occur only in freshness monitoring and metric target bands. | `aughor/ontology/models.py:289-340,502-503` · `aughor/ontology/lifecycle.py:1-20` · `aughor/monitors/runner.py:462` |
| "The investigation should start from the ontology" | **It never consults it first.** The pipeline predates the ontology (`investigate.py` 2026-05-20, `builder.py` 2026-05-26), so the ontology was bolted onto existing prompts as text: the deep coder's schema gets the relationship block, the intake is enriched with entity fields AFTER the question is parsed, the baseline plan gets an entity-context block. Nothing resolves a question's TERMS to an entity, a stage or a definition; nothing proposes drivers from the link graph. Consulting first has NO measurement — what was measured and retired (R4 92%→58%; ON-0/ON-0a no lift) is the text route, on questions the raw schema can answer. | `aughor/agent/investigate.py:1327,5866,6452` · `aughor/ontology/prompt_reach.py:294` · §6 item 15 |
| "Where can the dispatch question live?" | **Not on LuxExperience: every order ships within a day** (lag p50 0 · p95 1 · max 1 over 107,903 shipments; 0 never shipped — synthetic). **Olist (`baef6c3e/ecommerce`) holds the whole process plus a per-line promise:** `order_purchase_timestamp → order_approved_at → order_delivered_carrier_date → order_delivered_customer_date`, `order_estimated_delivery_date` per order, `order_items.shipping_limit_date` per line, sellers with a state, products with a category. Measured through `POST /query/run`: delivered after the estimate **7,826 / 96,478 = 8.11%**; handed to the carrier after the line's limit **10,423 / 111,456 = 9.35%**; approved→carrier p50/p90/p95 = **2 / 6 / 8 days**; office_furniture **28.4%** late dispatch, PR sellers **11.1%**. The data answers; the ontology cannot FRAME it — both deadlines are anonymous `timestamp` properties and "dispatched" is not a word the graph knows. | measured 2026-09-12 |

**The reading that reconciles the critique with the record.** The critique is right about the
NOUN layer, the SCOPE, the AUTHORING and the RULES. The record is right that a paragraph in the
prompt does not move accuracy. Both hold at once because the definition this arc is held to is
about what the agent can NAVIGATE and EXECUTE, not what it can read: an object type is what it
queries; a link is what it traverses; a rule is a definition executed once and never re-derived.
So this movement adds no prose to the prompt. It makes business meaning **executable** (a
promise becomes a verified segment and a metric target by construction) and **navigable** (a
question is framed against declared entities, stages and links before any SQL is written). Its
falsifier is a set where the raw schema FAILS because the definition is not in the data — the
set ON-0 never had.

**The reference platforms, honestly.** Foundry: an object type is backed by ONE dataset and the
pipeline layer does the joining; link types are DECLARED; the ontology spans every source because
every source is ingested first (`docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md` §1.3). Fabric IQ: an
entity type with SEVERAL bindings, declared relationships, static and timeseries properties, over
anything in OneLake (the 2026-09-11 amendment above). Snowflake Semantic Views: logical tables,
relationships, facts, dimensions, metrics — a semantic layer, per database. **None of the three
has a first-class business PROCESS with promises.** Foundry carries that in Actions and
Functions; process-mining tools carry it in event logs. A measured process is the natural
extension of ON-0a's law (the data wins), and ground none of them holds.

**Laws of the second movement (in addition to the standing laws above):**

- **The table is bound INTO the entity, never the reverse.** A business entity is a
  declaration; tables, keyed SELECTs and detail sources are bindings with a measured verdict.
  The builder's per-table entities become PROPOSALS a person or an explorer confirms, absorbs,
  renames or discards — and every existing graph deserialises unchanged (supersede, never
  delete: a per-table entity is a declared entity whose backing is its table, `origin: table`).
- **Every declaration is a claim the platform measures**, whoever made it — person, pack or
  explorer. A stage no row reaches, a promise the data never breaches, a link whose key covers
  nothing: reported as measured-false with its provenance, ON-0a's tiers unchanged. **Nothing
  the model says becomes a fact** (J4): an explorer's proposal carries `model:<id>@<version>`,
  is measured before it is shown, and is tiered `proposed` until a person confirms it.
- **Framing is deterministic first.** Terms resolve against declared names, aliases, stages and
  rules before a model is asked; the model chooses among candidates and words the frame; it
  never invents the definition. The frame is SHOWN with the answer.
- **The ERD stays a view.** The per-`(connection, schema)` measured graph becomes the SOURCE
  CATALOGUE — what tables exist, profiled, with join proposals — an input to the business
  ontology, never the ontology.

**Waves of the second movement. The user fixed the first: ON-7. The recommended order after it
is ON-7b → ON-9 → ON-10 → ON-8** (ON-9 and ON-10 are the only waves that change an answer and
carry the falsifier; ON-8 is shape work that changes no answer by itself) — the user's knob.

- ✅ **ON-7 · The declared entity, its parts and its links — FIRST SLICE BUILT + RECEIPT MET 2026-09-12**
  (the user: *"take on seven first"*; branch `claude/on-7-declared-entity`). **What exists:** `Binding.kind`
  gains `detail` (many rows per object, no clock) with `rollups` (`Rollup`: column + sum|avg|min|max|count),
  each computed inside the object's partition before the join (`aughor.ontology.parts.detail_from`) and read as
  a property like any other; `OntologyEntity.origin` (table | human | model) and `absorbed_into` — a part mark
  that HOLDS only while the parent binds the part's table (`parts.part_of`, one law for the bind door, the
  override and every read; a lapsed mark says so); `OntologyRelationship.origin`. Doors: `POST/DELETE
  /ontology/entities` (a declared type: its source read for columns and its key counted before anything is
  written, `aughor.ontology.declared`; a table that backs a type is refused — rename or absorb instead),
  `POST/DELETE /ontology/links` (each side counted, the share of keys that meet measured; a link whose keys
  NEVER meet is stored with `value_overlap` 0 and REFUSED by the compiler — found on the receipt, see below),
  the bind door's `absorb`, the entity override's `absorbed_into`. The overlay rebuilds a declared type and a
  declared link from what the door recorded, DB-free; the measure door re-counts declared links against a
  working copy that knows declared types (the cache stays raw). The builder proposes a table whose key REPEATS
  as a part (a detail binding with a `count` rollup). Web: the rail lists parts under the cards and offers *New
  entity*; a part's links are drawn from its parent's card, named through the part (`collapseParts`); the panel
  declares a detail binding with rollups (and folds the table's type in), adds a relationship by entity ids,
  shows parts and part-of, withdraws a declared type or link. **Receipts:** `tests/unit/test_object_parts.py`
  (16 tests: rollups equal hand-written references, the roll-up never multiplies, a part lapses when its binding
  goes, a declared type over a table and over a keyed SELECT, a declared link measured and traversed both ways,
  a link whose keys never meet refused, the doors end to end); `test_object_bindings.py`'s proposals updated for
  parts; web 839 green, seven gates green. **Live LuxExperience through the API, no model call:** Order ←
  order_items as `lines` (detail; 112,439 of 112,439 covered; OrderItem folded in) · Return ← return_logistics
  (static 50,048/50,048; ReturnLogistic folded) · Customer ← customer_service as `tickets` (detail; 7,841 of
  35,136; CustomerService folded) · Payment, Shipment → parts of Order · Price → part of Product ⇒ **the map
  reads 8 cards from 14 tables** (Order, Return, Product, Customer, Brand, Warehouse, Country, Date). Two links
  the builder never found, declared: `Order placed_by Customer` (N:1, 100% of keys held) and `Shipment
  ships_from Warehouse`. **Compiled = reference:** orders with more than 3 units 3,917 · GMV of top-customer
  orders through `placed_by` 18,384,951 · shipments by warehouse country through `ships_from` (Italy 37,372 …)
  · the ON-5 receipt still 1,744 · a part is still a type (191,093 order lines). 🔴 **Found by the receipt:** the
  first `ships_from` was declared on `warehouse = warehouse_id`; the measurement said N:1 with **0% of keys
  held** (shipments carry the warehouse's NAME), and the compiler still traversed it and answered NULL — a link
  the data refutes must be refused, not followed: `link_problem` now refuses a measured zero overlap (pinned).
  **Open on this wave:** ~~§6 item 18(b) — Payment and Shipment are parts on the receipt as drafted; one *Release*
  undoes it~~ — decided 2026-09-15, entities with a link, released and linked live on LuxExperience (§6 item 18(b)) ·
  ~~the agent's catalogue (`describe_entity`'s list, the prompt blocks) still names parts as types~~ — closed
  2026-09-15 (`eb663730`: the object catalog, the query tool's list of types and `describe_entity`'s summary name a part
  under its parent; the ENTITY MODEL block renders the raw build-time graph, which never holds a part mark) ·
  ~~a declared type does not round-trip through export/import~~ — closed 2026-09-15 (`1d4f1139`: declared types, links,
  processes and rules are written under `declared/` as their doors' specs and declared again on import) ·
  ~~line-grain access to a part's rows stays through the measured link (`order_to_order_item.category`), not through the
  binding's name~~ — closed 2026-09-15 (`a3eb8ad0`: a detail binding's name walks the one link to its rows' type). `POST /ontology/entities` declares an entity (display name,
  api_name, description, domain, a key claim); `POST /ontology/links` declares a link (business
  verb, expected cardinality, the key path between two bindings); `DELETE` for both, refusing
  where a consumer depends on the id (API names are stable). A third binding kind beside static
  and timeseries: **`detail`** — N rows per object on the object's key, no time axis (order
  lines, tickets, readings without a clock) — read at line grain, or rolled up to the object by a
  declared aggregation per property (`sum quantity → units`, `count → line_count`, `any returned`;
  `measure_grain` already knows per-unit from per-line). **Absorb a table as a part:** binding a
  table that is today an entity of its own marks that entity `absorbed_into` the parent — kept
  in the graph for byte-compatibility, hidden from the map and the agent's catalogue, its links
  re-pointed to the parent through the part. The map gains *New entity*, *Add relationship*,
  *Absorb as a part*; the builder's per-table entities carry `origin: table` and read as
  proposals. Migration by supersession: every cached graph, override file and `GET /ontology/*`
  payload deserialises unchanged. **Receipt:** LuxExperience as **8 business entities from 14
  tables** through the doors, no model call: Order {orders + order_items (detail) + payments +
  shipments}, Return {returns + return_logistics}, Product {products + price_history}, Customer
  {customers + customer_service (detail)}, Brand, Warehouse, Country, Date; every earlier
  compiled query (l05, l09, the bindings suite, the timeseries receipt) equal to its reference
  through the new shape; "orders with more than 3 units" compiles over the detail roll-up and
  equals its reference; the map reads 8 cards; a hand-written mutation set on the roll-up is
  caught (the ON-1b pattern).
- ✅ **ON-7b · The explorer maps the business first — FIRST SLICE BUILT + RECEIPT TAKEN 2026-09-13; the
  falsifier FIRED once, so the explorer stays on demand · MERGED #495, squash `3508a844`, 2026-09-13** (the user:
  *"Go for ON-7b"*; branch `claude/on-7b-explorer`). **What exists:** `aughor/ontology/explorer.py` — ONE model call over the SOURCE
  CATALOGUE (`source_catalogue`: every type with its key verdict, rows and columns with sample values; the
  builder's joins with measured cardinality and overlap; the bindings the data proposes; what is ALREADY
  DECLARED; the glossary for this scope's own tables; the bound pack's claims), answered as three flat lists
  (`BusinessDraft`: entities, parts, links). Every proposal is measured before it lands: a part's key is counted
  against its entity's objects and the DATA picks static, detail or timeseries (a model's time column on a
  one-row-per-object table is ignored; its rollups are kept only where the column exists, the aggregate is known
  and the name is free, else a `count`); a link whose keys never meet is refused; a declared entity's key must
  name one object per row. What survives is written through ON-7's own door bodies (`_bind_entity_core` ·
  `_declare_entity_core` · `_declare_link_core`) with `origin: model` and `model:<id>@<version>` provenance — the
  id of the binding that ANSWERED (`provider.answered_by`, set at the structured-call chokepoint and handed in
  by the router, so the ontology package imports no inference code and a fallback link is named rather than the
  model that was asked). Proposals are keyed by SUBSTANCE (the table under the entity, the two columns, the
  rows), so a second run writes nothing twice and a proposal a person withdrew or released is never proposed
  again; the record lives in `data/ontology_drafts` (isolated in conftest and `dump_openapi`), and a proposal's
  tier — proposed · confirmed · released · withdrawn · refused — is read LIVE from the served graph. Doors: `POST
  /ontology/explore` (its own trace, so its call reaches Spend and Activity) · `GET /ontology/draft` (with
  `reference_connection_id`: the grouping comparison) · `POST /ontology/draft/confirm` (all, or named
  declarations: `origin` becomes human, the provenance stays). The map's rail drafts, reviews and confirms;
  cards, links, bindings and parts say *proposed* until a person confirms them. **Tests:**
  `tests/unit/test_ontology_explorer.py` (the faux model over the seeded samples, through the real doors) and ten
  guard mutations, every one caught. **Live receipt — LuxExperience registered again from its file as
  `b428fce7`, its automatic exploration stopped at phase 4 before any model call; three model calls in all** (the
  build's enrichment and two drafts; `gemini-3.1-flash-lite`, no fallback). Draft 1 proposed 6 parts and 3
  links, and 8 landed: Order ← order_items as `lines` (detail: `total_units`, `line_count`), payments and
  shipments (static), customer_service as `tickets` (static); Product ← price_history (timeseries on
  `effective_date`); Return ← return_logistics (static); `Customer located_in Country`; `Product sold_by Brand`.
  `Shipment ships_from Warehouse` on `warehouse_id` was refused — shipments carry the warehouse's NAME. Draft 2
  did NOT repeat draft 1 (1 part and 4 links, at temperature 0): nothing was written twice — the 12 files draft
  1 wrote are byte-identical, two repeated links read *already*, `returns → Order` was refused as a part of a part
  — and two new measured links landed (`Brand originates_from Country`, 75% of keys meet; `Warehouse located_in
  Country`, 100%). Nine proposals confirmed; the fused one (below) left proposed for the user. **Compiled =
  reference, before and after confirming:** orders with more than 3 units 3,917 · top-customer GMV through
  `placed_by` 18,384,951 (a link this build found itself) · products whose latest price > €500 1,744 · order
  lines 191,093 · customers by country through the draft's `located_in` equal to the hand-written join (United
  States 4,860, Canada 4,769, Ireland 2,484). Shipments by warehouse country is NOT reachable: no `ships_from`.
  **The falsifier, against ON-7's hand-declared 8:** 8 groups each, 6 matched exactly (Brand, Country, Date,
  Product, Return, Warehouse), table-pair precision 0.67 and recall 0.89, and ONE FUSION — the draft reads
  customer_service under Order (each ticket names one order: 11,244 of 112,439) where the reference keeps it with
  Customer — so `ships_default_on` is false and the registration hook stays unwired. 🔴 **Found by the
  receipt:** the explore door ran without a trace and the session log drops a trace-less event, so draft 1's
  model call was metered and never recorded (fixed; draft 2's call is in the log under its run) · the panel
  kept offering *Bind* for four tables the draft had just bound — the builder proposes `schema.table`, the draft
  binds the bare name (fixed in code; reaches a running API on its next restart). **Open on this wave:** tickets
  under Order is the user's call (confirm, or remove the binding) · ~~a name join (`warehouse = name`) was guessed
  wrong once and not re-proposed~~ — closed 2026-09-15 (`8e442d4a`: a link whose keys never meet is counted again on
  the name its target is known by, when that name is measured one object per row) · run-to-run variance means a second
  draft ADDS rather than repeats (inherent to one call; recorded) · ~~the explorer proposes no processes yet (ON-9)~~ —
  closed 2026-09-15 (`3207f413`: processes and rules, measured before they land; live on LuxExperience's explorer record
  the same day, one call: two processes, two rules and a link written, one rule refused for an `=` given a list — and one
  process reads payment STATES as stages, captured → refunded → failed, which counting the objects in each state does not
  refute — withdrawn by the user the same day, so the explorer does not propose it again) · the explorer does not name the
  builder's found links — kept open ON PURPOSE: a model-written name would read as a person's, because a link carries no
  origin for its name and the confirm door no link-name target; that field is the next slice · two model-proposed links
  between one pair of types collide on the default reverse name (the explorer proposes none) · the §6 item 18(b)
  shape it drafted (Payment and Shipment as parts) agrees with the recommendation. When a
  connection is registered — or on demand from the map — an explorer agent reads the SOURCE
  CATALOGUE (table profiles, the join map with measured cardinality, sample values, glossary,
  the bound pack's claims) and proposes the BUSINESS ontology: which tables are one thing
  (entities with their parts), links with business verbs, domains, descriptions, and — once
  ON-9 exists — the processes it recognises. Every proposal is written through ON-7's doors as a
  claim with `model:<id>@<version>` provenance, MEASURED before it is shown (keys, coverage,
  cardinality), and lands as a DRAFT ontology the platform and its agents build on immediately,
  tiered `proposed` until a person confirms it in the map (provenance upgrades to `human`). This
  is the playground study's "not taken" line made safe: their generator loads unchecked output;
  ours measures every claim and keeps who said it. M12b's enrichment prompt becomes one input of
  this pass, not the only model pass. **Receipt:** LuxExperience re-registered from its file: the
  explorer's draft lands with its entities from 14 tables, each claim measured, the map showing
  proposed against confirmed; a second run over the same catalogue is idempotent (no duplicate
  proposals); the person confirms and the ON-7 receipt's queries still equal their references.
  **Falsifier:** the draft's grouping is compared with ON-7's hand-declared 8; a draft that fuses
  what the measured keys say are different things does not ship default-on. Costs model tokens —
  never started unasked.
- ✅ **ON-8 · One ontology, many sources — FIRST SLICE BUILT 2026-09-14** (the user: *"Lets go with ON-8 then.."*; branch
  `claude/on-8-many-sources`; §6 item 18(a) taken as recommended — `org/domain`, one default domain per organisation).
  **What exists:** the organisation's ontology is keyed `org/domain` and served by `aughor.ontology.domains.domain_graph` —
  no cache and no build. Its declarations live in the overrides tree under `org=<org>/<domain>` (a connection id never holds
  `=`, so there is no second store and every declaration kind works there unchanged) and are overlaid onto an empty graph on
  every read, with no database. `Backing.connection_id` and `Binding.connection_id` name where rows live ("" is the graph's
  own, so every graph built before loads unchanged); `OntologyRelationship.traversal` is `join | cross-source`, stamped by the
  SOURCE LAW (`aughor.ontology.sources`: a type reads its backing's connection, a binding its own, a link crosses when its
  two types differ) — the one law the compiler follows. **Measured across two connections under the verdicts one connection
  meets:** a binding's rows, keyed rows and distinct keys counted where they live, and its keys and the objects' read in the
  batched-foreach engine's canonical key form and met in memory (`measure_binding(object_db=)`); a link's two sides each
  counted on its own connection and its overlap met the same way (`measure_declared_link(to_db=)`); a side with more than
  2,000,000 distinct keys, or one its connection returns only partly, leaves the claim unmeasured. A declaration borrows its
  columns' roles from its own connection's catalogue and keeps the copy (`profile_record`), so the overlay needs no database.
  **The compiled door across two connections** (`aughor.semantic.cross_source`): a to-one link to a type on another
  connection, or a STATIC binding read from one, is a KEYED READ hanging off the query's own FROM level. The assembled
  statement is split with sqlglot: every expression that reads no far column and holds no aggregate is computed at HOME, on
  the anchor's connection, at the object's grain; each far source is read through the engine by exactly the distinct keys the
  home rows hold, one query per 1,000 keys, its values typed (`remote_join.fetch_by_keys` over
  `DatabaseConnection.read_typed_rows`, which takes plumbing labels only — a caller-facing one is refused); and the
  compiler's own SELECT, WHERE, GROUP BY and ORDER BY run over both in an in-process DuckDB STAGE, joined on the canonical
  key and dropped once read. Capped (250,000 home rows and 250,000 keyed rows; past a cap the answer is an error with the
  count, never part of the data); a far key that now meets two rows is refused rather than joined; every connection is gated
  before it is read and the answer passes the PII, audit and budget post-pass on the anchor's connection; every read is
  timed. Refused with the reason: a path past a far type, a to-many link or an EXISTS across connections, a keyed read inside
  a pre-aggregation or an EXISTS, far readings, a far binding that is not static, and a far type's own bindings. Doors:
  `?domain=` on `POST/DELETE /ontology/entities`, `PUT/DELETE /ontology/entities/{id}/bindings/{name}`, `POST/DELETE
  /ontology/links`, `POST /ontology/measure`, `GET /object-types` and `/object-types/{type}`, `/object-paths`,
  `/objects/catalog` and `POST /objects/query` (which returns `cross_source` and `timings`); `GET /ontology/domains`. One
  connection's ontology refuses a source on another and names `?domain=`, and its entity-edit door refuses the `domain:`
  scope the web carries. Web: the Ontology layer's **Domain** view — the entity-type map over every connection a type is
  declared on, each card and binding naming its connection, a cross-source link drawn dotted and labelled, the declare forms
  picking a connection (from another one a binding is static only); the doors that read one connection's graph (a display
  property, part marks, link names, the explorer, declared actions) are not offered there. **Tests:**
  `tests/unit/test_object_sources.py` (37: a warehouse split across two DuckDB files and written whole into a third — every
  cross-source count equal to the same claim on one connection, eight query shapes equal to the single statement row for
  row and three to hand-written SQL, every refusal, both caps, a repeated far key, the typed read's label rule, the gates, the
  doors over HTTP) and **41 guard mutations, every one caught** — the first run let one survive (the split's date-truncation
  fix is invisible on DuckDB; a BigQuery-dialect test now pins it); web: domain tests in `EntityTypeMap` and
  `EntityTypePanel`, `lib/objectTypes.test.ts`; seven gates green; `gen:api` run; web 889 green. **Live receipt:**
  LuxExperience through the running API, no model call, 2026-09-14 — the same ontology declared
  twice through the new doors: in `default`, Order on `914df862` and Customer and the order's shipments on `b428fce7`; in
  `reference`, everything on `914df862`. 🔴 Both registrations open the SAME file (`data/luxexperience_demo.duckdb`, read
  through `duckdb_databases()`), so this receipt times two connection objects, keyed reads and the stage — not a network;
  the unit receipt's separate DuckDB files are the physical two-source proof. Declared and measured across the two: Order's
  key 112,439 distinct of 112,439, Customer's 35,136 of 35,136; `placed_by` N:1 with 100% of Order's 29,048 distinct customer
  keys held, stamped `cross-source`; `shipment` (static, from `b428fce7`) 107,903 rows, one per order, covering 107,903 of
  112,439 orders with 0 orphans — every count equal to `reference`'s single-connection count. Five queries, each run five
  times on both domains, every answer equal row for row, and GMV by customer country also equal to hand-written SQL (35
  rows): GMV by customer country **1,382 ms across against 43 ms as one statement** (home 112,439 rows 253 ms · Customer
  read by 29,048 keys in 30 queries 890 ms · stage 179 ms); orders and shipping cost by carrier 4,310 ms against 52 ms
  (shipments read by 112,439 keys in 113 queries, 3,825 ms); average VIP order by service level 5,185 against 59; delivery
  days by customer region and fiscal year 5,175 against 63; distinct customers by carrier 5,080 against 66 (medians). The
  measure pass re-counted all of it in 583 ms, and the full backend suite ran once: 9,995 passed. **What the latency says**
  (§6 item 14(c): live resolution reopens only on a measured latency a cache cannot cover): the hop costs about 30 ms per
  1,000-key read, so it is priced by how many distinct keys the home rows carry — 30 reads by customer, 113 by order — not
  by the rows an answer returns; at 112,439 objects that is 1.4 to 5.2 seconds on one machine, and a remote warehouse adds
  its round trip to every keyed read. That is inside an interactive answer and the levers are named (fewer, larger keyed
  reads; the home side pre-aggregated at the key's grain), so the posture holds and nothing is materialised. 🔴 **Found while building it:** the engine's older door, `POST /query/cross-source-join`, returned rows
  the post-pass never saw. **Leftovers, second round (2026-09-15, branch `claude/on-leftovers-ii`; the user: *"Lets finish
  Arc ON leftovers back to back.."*):** ✅ **a cross-source answer passes the security gate once, for every connection it
  read** (`6c35fa35`) — measured first, and the premise was half wrong: the join's right reads and the federated driver
  were audited PER READ (#135), so they were redacted and budget-cut before the join (an email key met none of its rows;
  a right connection's row budget silently dropped joined rows), while the left read skipped the gate entirely; every
  read is plumbing now, and the answer is redacted after the join, held to the strictest row budget of the connections
  it read and audited on each · ✅ **the declare doors keep the provenance they are given** (`4eb8230b`; an
  organisation's doors refuse it, by §6 item 20) · ✅ **a read its connection cut is known to be cut** (`35d67e7b`) —
  SQLite, BigQuery, Exasol, MySQL and Snowflake reported the capped row count, so a cut key set or join input looked
  whole; each fetches one row past its cap, the Workspace and SQLite connections read past their caps when bounded, and
  the join refuses a cut left read and a join past its output cap, both of which it used to hand back as the whole ·
  ✅ **every connector hands back typed values and a bounded read** (`626827b3`) — the five DuckDB-backed connectors'
  copied execute became one shared read with typed capture and the JULIANDAY heal, and the four warehouses name their
  column types for the stage · ✅ **a query reads past a type read by key, and to-many links, EXISTS, timeseries and
  detail bindings cross as one row per key** (`00310eb9`) — a type or binding past a keyed read on that read's own
  connection is joined inside it, one on another connection is read by key from that read's rows, and every other shape
  is one row per key by construction; 13 new shapes, each equal to the single statement, 18/18 guard mutations caught.
  ✅ **the home rows are grouped at the key's grain** (`b1f5f916`) — COUNT, SUM, MIN, MAX and AVG pushed into the home
  read, weighted by each group's row count wherever a far value or a DISTINCT is read · ✅ **an organisation's ontology
  takes processes, rules and the frame door** (`f261054f`) and **opens its objects where they live** — the object page,
  the objects a link reaches, titles and a display property on a domain type (`1b1f9a3b`) · ✅ **platform SQL reaches a
  native-SQL warehouse in its own dialect** (`1278cee5`; a DuckDB `"col"` is the STRING 'col' on BigQuery, so a keyed read
  had matched nothing). **Still open on this wave:** a further crossing from inside a keyed EXISTS or pre-aggregation,
  refused with the reason · a domain type's description is not editable through its PUT (a display property only) · an
  organisation's object page reads findings from the home connection only. By the user's rule (§6 item 20) the explorer never reads
  an organisation's ontology and only a person edits it, and by the boundary that holds that rule the agent's tools read
  one connection's ontology; domain declarations are untracked override files, like LuxExperience's. The wave as drafted:
  The declared ontology is keyed by the organisation (or a
  named domain within it — §6 item 18), not by a schema; a binding names
  `connection_id.schema.table`; a link whose two sides live on different connections is
  `traversal: cross-source` and the compiler resolves it through the existing batched-foreach
  engine instead of one SQL; joins within a connection are unchanged. **Receipt:** one declared
  entity bound to tables on two connections, measured, its objects and one cross-source link
  readable through `/objects/query`; the latency of the cross-source hop on the receipt (it
  decides whether §6 item 14(c)'s live-resolution posture reopens — the draft said §4, which holds no federation entry).
- ✅ **ON-9 · Processes and promises — FIRST SLICE BUILT + RECEIPT MET 2026-09-13 · MERGED #496, squash `d92c14e8`,
  2026-09-13** (the user: *"Start with ON-9"*; branch `claude/on-9-processes`). **What exists:** `Process` · `ProcessStage` · `Promise` · `BusinessRule` on the graph
  (`OntologyGraph.processes`, `.rules` — a graph built before loads with both empty), declared through the overrides
  tree (two new kinds, `process` and `rule`: new directories, none renamed) and rebuilt with no database from what their
  measurement recorded (`aughor.ontology.processes`, `aughor.ontology.business_rules`). A stage is anchored to a MOMENT —
  a date or timestamp path from the type, to-one links only, a static binding's column included — or to lifecycle
  states. A promise is `within_days` of the previous stage (calendar days) or a per-object `deadline`, kept per object of
  its `grain`, which reaches the process's type through a measured to-one `via` resolved when it is declared (a
  marketplace's shipping limit is per LINE). **Every declaration is resolved by the compiler's own path law and COUNTED
  THROUGH THE OBJECT DOOR'S COMPILER** before it is written and on every measure pass and rebuild — measured by exactly
  the law it is read by: objects per stage; per transition both moments, skipped, out of order, and p50/p90/p95 calendar
  days (exact, from a per-day count any warehouse can run — equal to `quantile_cont`); per promise reached, broken,
  kept, open, and open past it as of the data's own latest moment. A stage no object reaches is measured-false; a
  promise never or always broken is FLAGGED, and the flag rides every compiled answer as a caveat. **Derived by
  construction** (`aughor.ontology.derived` — the door's own IR, never prose): `late_<promise>` (segment),
  `<promise>_breach_rate` (a ratio of two counts; target = the complement of a declared tolerance, none invented),
  `<promise>_lag_days` (calendar days between consecutive moments) — each refused with the reason until its declaration
  is measured. The compiler gains `value_path` (two properties of one object compared row by row, to-one only, the same
  kind of value) and `property_at`. A rule is a `value_set` (the packs' empty aliases filled: rows per value, a value no
  row holds flagged) or named `conditions` in the door's shape, read as a segment by its id. Doors: `GET/POST
  /ontology/processes`, `DELETE /ontology/processes/{id}`, `POST /ontology/rules`, `DELETE /ontology/rules/{id}`; the
  measure door reports both; `/object-types` carries processes, rules and what each type derives. Packs gain
  `processes:` and `rules:` as claims (kinds `process`, `rule`): a stage matched to a moment by name, a promise with its
  terms left to the business, settled as the person's where one is declared; `fashion-ecommerce` ships
  `order_to_delivery` with placeholder promises and DACH as an empty value set. Web: the map's rail lists Processes
  (each promise's measured breach rate) and Rules; a process opens in `ProcessPanel` (stages, timings, promises with
  exact counts, flags in red, derived names, a two-click withdraw); the type panel gains "Processes and rules". Nothing
  reaches a prompt. **Tests:** `tests/unit/test_object_processes.py` (44: every count held to a hand-written query over
  the samples warehouse plus a per-line `ship_by` deadline; the doors end to end) · 3 pack-claim tests · **16 guard
  mutations, every one caught** — the first run let one survive (the overdue cutoff moved a day and no fixture object
  sat on the boundary), now pinned object by object on the boundary · web `ProcessPanel.test.tsx` (5); seven gates
  green; `gen:api` run. **Live receipt — Olist on `baef6c3e/ecommerce`, through the API, no model call:**
  `order_to_delivery` declared as placed → approved → dispatched (promise ≤ `shipping_limit_date`, kept per OrderItem via
  `order_item_to_order`) → delivered (promise ≤ `order_estimated_delivery_date`). Every count equals its hand-written
  reference: stages 99,441 · 99,281 · 97,658 · 96,476; approved→dispatched p50/p90/p95 **2/6/8 days**, with **1,359
  orders handed to the carrier BEFORE approval** and 14 with no approval at all; dispatched→delivered 7/19/24; **the
  dispatch promise broken on 10,423 of 111,456 lines (9.35%)**, 1,194 lines never dispatched, 1,193 of them past their
  limit as of 2018-09-11; **the delivery promise broken on 7,827 of 96,476 orders (8.11%)** — the table above counted
  7,826 of 96,478 by STATUS; the process counts by the MOMENT (one late delivery sits on an order whose status is not
  delivered, and eight delivered orders carry no delivery moment). Derived, through `/objects/query`: `late_dispatch`
  10,423 · `dispatch_breach_rate` 9.35 · `late_delivery` 7,827 · `delivery_breach_rate` 8.11 · the breach rate and the
  lines reached per product category, all 74 rows equal (office furniture **28.37%** over 1,678 lines) · per seller state
  (PR **11.09%**) · mean `dispatch_lag_days` 2.7072; rules `southeast` 2,287 sellers (SP 1,849 · MG 244 · RJ 171 · ES 23)
  and `fulfilled_orders` 98,207; a comparison across a to-many link refused. `POST /ontology/measure` counted both again
  and no number moved. **Second receipt — LuxExperience (`914df862`):** `order_to_shipment`, shipped within 2 calendar
  days of placement, the moment read through the `shipments` static binding: 107,903 reached and **0 broken — FLAGGED
  "never broken"**, which is exactly what a synthetic 0–1 day lag should earn (4,536 orders never shipped, 4,528 past it
  as of 2025-06-30 — both equal to references); the map shows it in the rail and the panel. 🔴 **Found by the receipt:**
  (1) the Intelligence workspace offers only the schema a connection's registry names, so Olist's `ecommerce` ontology —
  and the process declared on it — cannot be opened in the web map at all (a chip is filed; the API reads it) · (2) a
  declaration path refused a column named with a space (`Order Date`) that the door itself resolves — relaxed to any
  name without a dot, a quote, a backtick or a semicolon · (3) the first mutation run found the overdue boundary
  untested. **Open on this wave:** ~~the explorer (ON-7b) proposes no processes yet · no web form declares a process (the
  API does) · a `condition` rule reads as a segment and does not yet scope a metric ("revenue excludes cancelled")~~ —
  closed 2026-09-15: the explorer proposes processes and rules (`3207f413`), the type panel declares both (`aa0df234`),
  a rule scopes the verified metrics it names (`89ebf974`), and the Intelligence workspace offers every schema a
  connection's ontology is built on (`3db7a759`, the receipt's finding (1)) · derived metrics stay out of `graph.metrics`
  and the metric contract ON PURPOSE (no prompt reach) — ON-10 is where a frame reaches the investigation ·
  ~~a promise in hours is not expressible~~ — closed 2026-09-15 (`d1a02ce9`: the hours that pass, not the calendar days
  they touch) · the Olist and Lux declarations are UNTRACKED override files. The wave as drafted: `Process`: ordered `Stage`s, each anchored to (entity,
  timestamp property | lifecycle state); a transition may carry a **promise** — a fixed duration
  (`within 2 days`) or a per-object deadline property (`shipping_limit_date`,
  `order_estimated_delivery_date`). `Rule`: a named, owned definition with scope and formula
  ("revenue excludes cancelled and refunded", "DACH = DE, AT, CH" — the packs' empty `aliases`
  filled at last). Both measured on declaration and on every rebuild: per transition p50/p90/p95
  and breach rate; a promise never or always breached is flagged. From a measured promise the
  platform DERIVES, by construction, a verified segment (`late_dispatch`), a computed property
  (`dispatch_lag_days`) and a metric whose target is the promise (`dispatch_breach_rate`), so
  "what is late" is executed once. Packs gain `processes:` and `rules:` (fashion-ecommerce ships
  order-to-delivery with placeholder promises). **Receipt:** Olist declared as Order-to-delivery:
  placed → approved → dispatched (promise `≤ shipping_limit_date`) → delivered (promise
  `≤ order_estimated_delivery_date`); the measured breach rates equal the table above; the
  derived segment and metric compile and equal their references.
- ✅ **ON-10 · The investigation starts from the ontology — FIRST SLICE BUILT + LIVE FRAME RECEIPT 2026-09-13; THE
  FALSIFIER HELD TWICE 2026-09-13 — OLIST FRAMED 8 OF 12, RAW 3; LUXEXPERIENCE FRAMED 9 OF 13, RAW 1 · MERGED #497, squash `73a61047`, 2026-09-13** (the
  user: *"Take whats next on the ontology roadmap"*; branch
  `claude/on-10-framing`). **What exists:** `aughor.ontology.framing` — pure: no model, no store, no warehouse.
  `frame_question(question, graph, synonyms, hops)` matches the question's words (a small deterministic stemmer; a longer
  declared name wins its words over a shorter one of no higher rank) against what was declared — types by id, display
  name, api name and backing table; readable properties with a generic tail dropped, and a short name without the type's
  own words; a person's synonyms (the human tier only); processes, stages, promise nouns, what each promise derives, and
  rules — and returns the FRAME: the OUTCOME (a promise — its late segment and breach rate —, a lag, or a rule) in the
  declaration's own words with its measured note; where to START (the type the promise is kept per, its backing, whether
  its key is unique); the RULES applied from the start through the measured to-one link path (a rule on a type the start
  cannot reach is said and never applied); the stage MOMENTS named ("placed in 2017" → `order_purchase_timestamp`); the
  candidate DRIVERS — dimensions reachable by measured to-one links within N hops (default 2, at most the compiler's 3),
  the ones the question names first; and each definition COMPILED by the object door, schema-qualified. What the words ask
  decides between a stage's promise and its lag ("late", "breach", "on time", "worst record" → the promise; "how long",
  "lag" → the lag; "delay" by what stands beside it). "Late" with no stage named makes every promise a candidate, ranked
  by the grain the question names and by whether the promise's type reaches what it names — so Olist's *"which
  categories are always late"* reads as the dispatch promise, because the delivery promise is kept per Order and an Order
  reaches no category by a to-one link; words that fit two promises equally choose neither. A short name repeating the
  tail of a property named in full is that property again, and a homonym no type reaches (Olist's translation table's
  category column) never vetoes the property a promise's type does reach. Builder-made segments and metrics are terms that define
  nothing: the validator proves a guessed filter executes, not that the business means it. `aughor.agent.framing` reads
  the served graph under the ontology doors' scope law and, only when the words fit several declared definitions
  equally, asks the fast model to choose — a name that is not listed chooses nothing. **Wiring:** `/investigate` frames
  the question before the graph starts and emits a `frame` event (declared in the web's part vocabulary); the deep
  analysis's intake prompt, the filtered schema every phase planner reads, and the explore chain planner carry the frame
  block; the named drivers lead the intake's dimensions; the reading joins the Investigation Specification; the answer
  report carries `frame`. **A question that reaches nothing declared leaves the intake prompt byte-identical** — a test
  compares it with the prompt the intake wrote before ON-10. Door `POST /ontology/frame` (no model, no warehouse). Web:
  `QuestionFrame` — "Read as", with the definition, rules, start and drivers in a fold — on deep and explore answers and
  while one streams. Harness: the `framed` arm (dropped where nothing is declared; no call spent on a question that
  reaches nothing, which is scored as raw; one extra call only for an ambiguous frame) and the falsifier by `definition`
  label; `evals/ablation_olist_business.jsonl` — 12 questions whose definition is declared, 3 controls, every reference
  executed through the API and again through the harness (15 of 15), the served graph frozen beside it. The prompt-reach
  audit registers the frame block: its fixture gains a process with two promises and a rule — 317 fields walked, 43
  reach the frame. **Tests:** `test_ontology_framing.py` (every compiled definition held to a hand-written query over
  the samples warehouse, the door end to end) · `test_agent_framing.py` · `test_ablation_framed_arm.py` ·
  `test_intake_frame.py` · web `QuestionFrame.test.tsx` and a turn projection test; the vocabulary, prompt-reach and
  SSE-parity ratchets updated; **29 guard mutations, every one caught** — the first run let three survive: named drivers
  were put first twice over (the sort half was dead), the chooser's own no-call guard hid behind its callers', and the
  byte-identical intake test compared two runs of the SAME mutated line (it now compares with the prompt written before).
  **Live receipt — through the running API, no model call:** on Olist 15 of 18 questions reach a declared definition —
  the 12 declared-definition questions of the set, the critique's *"What is causing a delay in warehouse dispatch?"*,
  *"Which categories are always late?"* and an ambiguous *"What was late last month?"* — and none of the 3 controls; the
  compiler refused no definition. The dispatch question reads as the dispatch promise (10,423 of 111,456 lines, 9.35%),
  starting from Order Line (`order_items`, whose key is not unique), testing product category, seller state and order
  status; the ambiguous one lists both promises and chooses neither. On LuxExperience the same dispatch question reads
  as the shipping promise and carries its "never broken" flag — the frame itself says the synthetic data cannot answer
  it. **The falsifier run** (the user: *"continue with Falsifier run"*; 2026-09-13; `gemini-3.1-flash-lite`, fallback
  none; 27 SQL calls, two transient errors each retried once, none spent choosing — no question of the set was
  ambiguous; the graph frozen beside the set hash-equal to the one the API served that day; results in
  `evals/ablation_on10_olist_business_results.json`): **THE FALSIFIER HELD — on the 12 questions whose definition is
  declared, framed answered 8 and raw 3 (guarded made 5 safe); framed lost none raw answered and kept all 3 controls.**
  The five gained are definitions raw guessed from column names: the dispatch promise read as delivery to the customer
  after the shipping limit (79.12% where the business measures 9.35%) or as late delivery (Southeast 8.03% where the
  promise reads 9.16%), and "fulfilled" read as `order_status = 'delivered'` (43,428 orders placed in 2017 where
  finance's rule counts 44,379; every year's line total low; 98.24% delivered where the rule's population reads 98.23%
  — the thinnest of the five). The three framed still missed are dispatch BREAKDOWNS on which framed named the
  reference's categories, states and month in the reference's order while raw, reading the promise as late delivery,
  named others: twice the model rounded the compiled rate — a fraction — without ×100 where the question asked for a
  percentage (PR 0.11 for 11.09, February 0.13 for 13.25), and once it rebuilt the grouped rate over every line instead
  of the lines that reached dispatch (28.15 for 28.37). The lag question failed in every arm alike: the model wrote
  SQLite's `JULIANDAY` against DuckDB with the frame's compiled `DATE_DIFF` in front of it. **What the run does not
  show:** it is one run of one model on 12 questions, and the matcher's reading of these 12 was developed on these very
  questions (the live receipt framed them) — the model half is out of sample, the matcher half is not; a held-out set on
  another host measures that. **The held-out run on LuxExperience** (the user: *"I would like to run tests on
  Luxexperience schema.. Olist is small fish.."*; 2026-09-13; same model, fallback none; results in
  `evals/ablation_on10_luxexperience_business_results.json`). Lux declared nothing a frame could resolve — no rule, one
  promise never broken — so, with the user's go, seven rules and a process were DECLARED LIVE on `914df862` through the
  ON-9 doors, each counted before it landed: completed orders (shipped or returned, 107,903 of 112,439), VIP customers
  (the VIP and Top Customer tiers, 4,576 of 35,136), EU markets (the 12 EU states shipped to — Ireland in; the UK,
  Switzerland and Norway out), YNAP (its four platforms, whichever group reported the order), controllable returns
  (quality, not as expected, late delivery), high-risk payments (a fraud score of 0.2 or more: 143 — the fraud flag is
  never set) and the accessories division (bags, shoes, jewellery and watches, accessories); `return_to_refund` promises
  a refund within 10 days of the return arriving, broken on 11,648 of 50,048 returns (23.27%). The set
  `evals/ablation_luxexperience_business.jsonl` — 13 questions whose definition is declared and 3 controls, every
  reference executed and checked to differ from its column reading before any call — was written for those
  definitions, and the matcher stayed frozen: its dry run's defects were recorded, not fixed. 28 SQL calls (one
  transient error retried once), none spent choosing. **THE FALSIFIER HELD AGAIN — framed answered 9 of the 13, raw 1
  (guarded made 5 safe); all 3 controls kept.** Raw read every term from the columns: completed as `status = 'shipped'`
  (12,872 for 21,405), VIP as `tier = 'VIP'` (5.60% of fiscal 2025 GMV for 46.51%), EU markets as the Europe region
  (7,352 orders for 7,727; Norway in Ireland's place among the top three), YNAP as `parent_entity` (4,642,040 for
  5,477,983), the accessories division as `category = 'accessories'` (5.80% for 32.63%), and the refund promise as any
  refund after the request (100% broken for 23.27%, every carrier alike). **Framed lost one:** asked what share of
  completed orders had a return, it applied the rule, then divided by orders repeated by its join to returns (37.33 for
  39.89) — where raw, reading completed as not cancelled this time, counted distinct orders. **The held-out matcher:** 11
  of the 13 questions it had never seen framed; the two it missed put the words in another order than the declared
  name ("returns were controllable", "payments were high-risk"), so they scored as raw — which invented controllable as
  size, not as expected and quality (74.09% for 37.97%) and read high-risk as the never-set flag (0.00% for 0.13%).
  Three frame defects cost no answer this run: an answer instruction's "Return the region" read as the Return type (a
  spurious note in those frames); "GMV from VIP customers" started from Customer, the rule's type, not Order; "return
  the country" named the customer's country, not the ship country. One control framed ("express shipments" read as the
  shipped moment) and stayed correct. The lag question failed in raw and framed as on Olist — `JULIANDAY` on DuckDB
  with the compiled `DATE_DIFF` in front of it: two lag questions, two hosts, the same failure. The run shares Olist's
  limits — one run, one model — and adds its own: the same hand wrote the definitions, the questions and the references,
  for a synthetic business the user owns. **JULIANDAY repaired** (the user: *"Repair SQLite JULIANDAY written against
  DuckDB"*; 2026-09-13): the eval harness's generators (`evals/run_golden.py` — the ablation, golden and bake-off runs)
  and the in-product benchmark runner built `CHAT_PROMPT` without the engine's dialect rules, the DuckDB block that
  forbids JULIANDAY by name and that the quick path, the deep writer and agent evaluation already carry; each now leads
  with them, and a guard finds every `CHAT_PROMPT` builder by parsing and fails one that does not reach them. DuckDB's
  refusal is healed where SQL runs: `DuckDBConnection` and `LocalUploadConnection` retry a refused one-argument
  JULIANDAY once as `(julian(CAST(x AS TIMESTAMP)) - 0.5)` — SQLite's own number, tested against the standard
  library's sqlite3 — the audit log records the statement that ran, and the eval scorer, which bypasses the
  connection, heals the same way. With no model call the four lost statements now answer through the product's
  connection: Lux's framed refund lag 6.50, its reference; raw's 12.01, the lag counted from the request; Olist's 2.81
  in both arms, fractional days where the declared lag counts calendar days (2.71). 16 guard mutations, every one
  caught. **The matcher's four gaps fixed** (the user: *"then 'Fixing the matcher gaps needs a new question set to
  measure' thing"*; 2026-09-13), measured with no model on a set committed BEFORE the matching code was read or changed:
  `evals/framing_matcher_set.jsonl` — 54 natural questions over Olist and LuxExperience, each with a gold frame (the
  definition it means, the rules that apply, the start, the breakdown it names, terms that must not appear), tagged by
  gap and split dev/test by alternation — scored by `evals/framing_matcher_eval.py`. Baseline, in scope: dev 10/29, test
  11/22. The fixes, in `aughor/ontology/framing.py`: a rule's name matches with its words in another order within one
  sentence ("returns that were controllable"), weaker than its spelling and covering nothing; an answer instruction's
  verb — a clause's first word before a determiner, "Return the region", "Order each category" — names no type (a
  plural heading a clause is a noun); rules read alone start from a type the question names that reaches every rule's
  type by measured to-one links ("orders placed by VIP customers" counts orders), two rules alike; and a word that fits
  several properties is narrowed only where the question says which — to the property a rule in the frame is defined on
  ("EU markets … the country" is `ship_country`, now also named by its last word), else to a type the question names in
  other words — while a bare word keeps every property it fits. After: dev 29/29; the test split, measured once, 21/22 —
  the narrowing had broken "In which country do VIP customers live most often?", because the word "country" also names
  the Country type and narrowed to it; corrected (a type narrows only when OTHER words name it), test 22/22, that item
  no longer held out. Paraphrases stay 0/3. On the two falsifier sets 5 of 34 frames changed, each a LuxExperience
  defect: the VIP GMV question starts from Order, "Return the country" names `ship_country`, controllable returns and
  high-risk payments now frame, the carrier is named once; no Olist frame moved. 12 guard mutations, every one caught.
  **Open on this wave** (the leftovers' second round, 2026-09-15, closed most of it): ~~a frame that states its rate's
  unit~~ — built (`e29fb3e9`: "is a FRACTION of 1 … multiply by 100 when the question asks for a percentage") and
  measured 2026-09-15 on a NEW set of six rate questions (`evals/ablation_*_rate_units.jsonl` →
  `evals/ablation_rate_units_results.json`; openrouter `deepseek/deepseek-v4.1-flash`, 12 generation calls): framed 5 of 6
  against raw 2 of 6, every framed answer a percentage — raw's four misses were definitions (all lines as the denominator,
  14 days counted from the request), framed's one a numerator slip · ~~a rule read alone that counts ITS OWN type while the question names
  another that reaches it~~ and ~~rules alone that tie still send the model to choose~~ — closed (`b159888a`, measured on
  8 matcher items committed before the change, `0a805eee`: dev 33/33, test 27/27) · a definition asked in words nobody
  declared needs a person's synonym (by design) · ~~the declare doors drop `provenance`~~ — closed (`4eb8230b`) ·
  ~~the framed arm is not guarded in the harness~~ — closed (`0ea46cc2`: the `framed_guarded` arm, held to the safety
  guarding already keeps) · a second run of both sets and a live deep analysis showing the frame in the web — done 2026-09-15 on the model the
  platform is set to now (`deepseek/deepseek-v4.1-flash`, not the first runs' gemini flash-lite: a replication across
  models, not same-model noise): Olist declared raw 4 · framed 11 of 12 (first run 3 · 8), LuxExperience raw 2 · framed 13
  of 13 (first run 1 · 9), controls kept, the guarded framed arm as safe as framed, every earlier framed miss now correct
  and one new Olist miss (ob09); 93 generation calls (`evals/ablation_on10_*_business_rerun_results.json`). The web
  chat's deep analysis on LuxExperience shows the frame live: "Read as" the declared refund promise with its measurement,
  and "How the question was framed" — definition, start, the drivers the declared links reach, and a note on a type they
  do not. The run itself (8 minutes, 7 steps) found where refund breaches concentrate and said plainly that no query returned
  the carrier its question named: it took the scan route, where breakdowns by the frame's drivers are still the next
  slice · ~~the frame is not yet a phase of compiled breakdowns~~ — a first slice built
  (`e29fb3e9`: the deep analysis's named breakdown runs the breakdown the frame compiled for its chosen promise or lag);
  breakdowns by UNNAMED candidate drivers are the next slice · the model does not word the frame — kept ON PURPOSE: the
  deterministic reading is free, exact and says only what was declared and measured, where a model-worded one would
  spend a call per question to paraphrase definitions it could re-derive in prose · ~~the explorer proposes no
  processes~~ — closed (`3207f413`) · ~~the conversational agent does not frame~~ — closed (`d2173f49`: the quick answer
  frames, and the conversation's answer tool calls that same `answer_core`) · the prompt-reach baseline grew twice, on
  purpose and recorded: a promise within hours and a promise's measured rate reach the question frame. The wave as drafted: A `frame_question` step BEFORE the
  investigation's and the deep analysis's intake parse — today the ontology is consulted only
  after (the table above): resolve the question's terms (entity names, aliases, stage names,
  rule and metric names) → the frame: entity, process + stage, the rule or promise that defines
  the outcome, the start binding, and **candidate drivers** = dimension entities reachable by
  declared links within N hops (category through Product, brand through Brand, seller state
  through Seller, warehouse through Shipment). Deterministic where names match; the model
  chooses among candidates and words the frame; the frame is rendered into the intake, drives
  the baseline plan (the planner already takes `render_entity_context`; ON-2's compiler already
  produces breakdowns by linked dimensions) and is SHOWN with the answer: *"Read 'dispatch delay'
  as stage Dispatched of Order-to-delivery breaching `shipping_limit_date` (9.35% of lines);
  testing category, seller state, carrier."* **Receipt and the movement's falsifier:**
  `evals/ablation_olist_business.jsonl`, 12–15 questions whose definitions are NOT in the schema
  ("what is causing dispatch delays", "which categories are always late", "how is the delivery
  promise doing by seller state", "returns turnaround against the promise"), every reference
  executed; arms `raw`, `guarded`, `framed`. **If the framed arm does not beat raw on the
  definition-dependent questions, the movement stops at ON-9's declarations and the framing is
  retired the way ON-6 was.** Costs model calls — never started unasked.

**Hosts.** ON-7's receipt on LuxExperience (shape, no delays needed). ON-9/ON-10's receipts on
Olist (`baef6c3e/ecommerce`, real delays, no generator change); ON-10's second, held-out falsifier on
LuxExperience, through definitions declared live there (7 rules and a refund process, 2026-09-13); the LuxExperience pack's
generator may later grow realistic dispatch lags so the demo pack can host the question (§6
item 18). **Open for the user — §6 item 18:** whether Shipment and Payment are PARTS of Order (today bound as static
1:1 sources) or entities with a link; Olist first against enriching the Lux generator. (Its first question, the scope key
for ON-8, was taken as recommended when ON-8 began, 2026-09-14.)


### 3.16 · Arc UI — Instrument, the design system (adopted 2026-09-13 — §6 item 19; **FIRST PASS BUILT** the same day; **PASSES 1–3 MERGED #498, squash `4476507d`, 2026-09-13**)

> **Origin.** The user, 2026-09-13: *"Lets scoop up a UI overhaul.."*, handing off the Claude Design project
> "Aughor Design System" (`Aughor Design System.dc.html`: tokens dark and light, type, components, the shell dark
> and light, the four universal states, the trust system, motion, icons and density). The spec in this codebase's
> names, with everything adoption decided, is **`web/aughor-v2/INSTRUMENT.md`** — read that, not this summary.

**The thesis.** Aughor's product is a claim about a number, and the interface's whole job is to make that claim
checkable at a glance: one warm monochrome plane, hairlines for structure, colour as a data type, three things
that float (popover, toast, dialog), no spinners, and motion only where it explains a state change.

**First pass — built on branch `claude/instrument-overhaul`, 2026-09-13.** The scope was the user's call before a
line was written (§6 item 19a): tokens, type, motion, the primitives and the shell chrome — no new features.
- **Tokens.** `aughor-v2/theme/tokens-v2.css` is the Instrument set: 41 values per theme, aliases as real `var()`s,
  motion `--dur-1/2/3` with the older names pointed at them. The v2 `elevation-motion.css` (glass, lift, spring) and
  `components-v2.css` (a second component layer) were folded into `app/globals.css` and deleted.
- **Components.** The `.aug-*` layer rewritten to the component sheet; `components/ui/*` redrawn (button, badge,
  input, textarea, select, tabs, tooltip, dialog, card, table, progress, scroll-area, separator, empty-state,
  motion, toast, MiniStat) and `StatusChip` with them.
- **Shell.** Wordmark, workspace switcher, ⌘K field and user menu in the 48px topbar; a 248px rail of 22px items
  with one `--blue3` active bar; 44px content headers; every workspace layer switcher segmented.
- **Sweeps.** 22 spinners became the ◐ pending mark or skeleton rows; card and node shadows removed (floats keep
  the token shadow); 491 text colours moved `--t4 → --t3` (§6 item 19c).
- **Palette.** `lint:palette` learned to resolve `var()` aliases; the charts are the intent hues, four of them
  moved the minimum the validator needed (§6 item 19b); the chart SSR bundle was rebuilt.

**Not built yet — the rest of the spec** (INSTRUMENT.md §9): the topbar LIVE activity strip, the topbar theme
toggle, the Human / Agent / Substrate switcher and nav badge counts; the trust system as shared primitives (guard
chip, receipt chain, confidence, citation, why-this-number, refusal); error and partial as primitives; and the
~30 components that still carry raw hexes.


### 3.17 · Arc IP — industry packages: one playbook per industry, chosen at install, read for the connection's own industry (drafted and adopted 2026-09-14 — §6 item 21, all nine answers; **IP-0 BUILT** the same day, **MERGED #503**, squash `aebe5feb`, 2026-09-14; **IP-1 and IP-2 MERGED #518**, squash `1c150b05`, 2026-09-17; **IP-3 MERGED #519**, squash `21a4484f`, 2026-09-17; **IP-4 MERGED #520**, squash `7e13f64e`, 2026-09-17: gate 6 enforced, banking & lending through gates 1–4 — and the package ships `status: draft`, which by gate 6's own rule means no agent reads it until a person activates it)

> **Origin.** The user, 2026-09-14: *"With a hope that our Explorer agents curator agents briefing agents analyst
> agents are reading the playbook and taking it as a reference for business analysis, I think we should have packages
> of the playbook which the user can choose from during installation. Each package would be one industry such
> ecommerce and aviation that we have right now. Scan the web for top such business and lets draw a plan to generate
> playbooks for them."* The research is three studies in `docs/`: `INDUSTRY_PACKAGES_RANKING_STUDY_2026-09-14.md`
> (29 industries scored), `INDUSTRY_CANON_REGULATED_STUDY_2026-09-14.md` (10 industries) and
> `INDUSTRY_CANON_COMMERCE_STUDY_2026-09-14.md` (14 industries, and a gap check of the six we ship).

**The premise, read in the code and probed on main `0f1eb220` — the playbook was read in part, and never for one
industry.**
- The Explorer read the most: the matched industry KB's curated metrics (up to 10 recipes), four plays per domain,
  and the deep KB through vector search, which needs an embedding model.
- The Analyst's synthesis and the Responder read plays ranked by word overlap across all 392, whatever the industry;
  the synthesis block called them "proven interventions" and told the model to prefer them.
- The Curator's birth job read no KB and no play — only the ontology claims of a pack a person had bound.
- The Briefer read the industry's name and its north-star metric names.
- There were six industries, not two: retail/e-commerce, airline, food delivery, logistics, manufacturing and SaaS
  (`data/kb/industry/*.json`, with deep-KB files such as `ec_*` and `airline_operations`).

**IP-0 · An honest playbook — BUILT `9a986534`.** Four defects and a label, each measured by a hermetic probe on a copy
of the live `data/playbook.json` (nothing written, no model called):
- **Industry scope.** 21 of 96 plays across 24 probe questions came from another industry — "why is churn up this
  quarter" on SaaS drew four e-commerce plays. `retrieve_for_metric_and_phases` takes `industry=` from
  `metric_kb.industry_scope`: the organisation's declared industry, else the connection's STORED profile, never an
  inference. A curated id reads that industry's plays and the shared ones; "" (known, uncurated) the shared ones only;
  None (unknown) everything. The Explorer, deep-analysis synthesis, chat answers, the investigation stream and
  definitional answers all pass it. The same probe returns 0.
- **The seed.** `cause.get("cause") or cause if isinstance(cause, str) else ""` parses as a conditional over the whole
  `or`, so all 486 inflation and deflation causes — each with detection SQL and a fix — became "" and were skipped.
  Fixed, and the seed is one write (`store.save_entries`): 878 plays in 0.08 s, where the 392 took 3.8 s of awaited
  startup. Data-quality plays stay out of every read unless a caller asks for them.
- **Industry matching.** `match_industry` was a substring test: "Retail Banking" got the retail KB and "Online Travel
  Marketplace" the food-delivery one. It matches whole words now; a KB's `generic_aliases` decide only when no specific
  alias matches and the text names no uncurated industry; a tie abstains. Every live profile still resolves to retail.
  The union-of-all-KBs vocabulary for an unmatched industry is unchanged.
- **Definitional answers** called `.get()` on `PlaybookEntry` models into a bare `except: pass` and never carried a
  play. They do now, and their three swallows go through `tolerate()` (ratchet 214 → 211).
- **The label.** The synthesis block says "proven" only when a play has a logged outcome.
- **Receipts:** `tests/unit/test_industry_match.py` and `tests/unit/test_playbook_reads.py`; the full backend suite
  once on the commit, 9,998 passed, 5 skipped. **Merged** as #503 (squash `aebe5feb`, 2026-09-14) after #502, which edits the same
  retriever call: the explorer's read passes both `learned_rates=False` and the industry scope.

**IP-1 · The package seam — BUILT 2026-09-17, MERGED #518** (squash `1c150b05`, with IP-2) and deployed the same day:
the live playbook topped up from 392 to 878 plays (the 486 checks, all active; 459 with a fix), no model call at boot.
- **The seam.** The KB left `data/kb` for eleven packages, content untouched (69 `git mv` renames): six industry packages
  (airline, food-delivery, logistics, manufacturing, retail, saas — each its curated `industry.json` and its deep KB
  files), four functions every industry reads (finance, marketing, product, customer) and `analytics-base`. `pack.yaml`
  declares `layer` and `industry`. `aughor/packs/knowledge.py` is the one reader that replaced the four loaders (the
  seeder, the profiler, the industry KB, the vector retriever): an entry's industry is its package's, authored wins an
  id, a deprecated package is not read, a file or an industry carried twice is a named problem, UTF-8 everywhere.
  **Moved unchanged, measured:** `tests/fixtures/ip1_kb_parity.json` was captured from the pre-move loaders on
  `4c4358b6`, and the parity tests reproduce all of it through the packages — 878 plays by kind and industry with
  identical content, 282 retriever entries, the profiler's stems, the six industries, every entry's industry, each
  industry's vocabulary. The full backend suite on the seam commit: 10,551 passed, 5 skipped.
- **Data-quality plays reach the Verifier as rule-outs** — the user's call, 2026-09-17, asked twice and answered the
  same: *"Rule-outs on reports"*. The detection queries are NOT run: they name example tables, and a row back would show
  that the data has the shape where a pitfall can happen, not that the analysis made the mistake. When a deep analysis
  reports its metric moving, `Verifier.rule_outs` lists the metric's known inflation causes (it rose) or deflation
  causes (it fell), each with its fix, and says *"Not checked against your data."* — carried in the data, so no surface
  can render the causes without it. Deterministic: no model, no query. Three reads (`aughor/playbook/rule_outs.py`):
  the **direction** is the sign of the report's own `total_change_label`, on a report measured against something; the
  **metric** is named when a KB entry's title or intent tag ENDS the report's label — a one-word alias must be the
  whole label, and a bracket restating the measure as a count abstains; the **plays** are the playbook's active
  data-quality plays for that entry and direction in the connection's industry scope, each listed with its version and
  receipt and journaled as a `playbook.use`. **Measured on the 202 deep reports stored on the builder's deployment:** 19
  state a signed move against a comparison; 9 name a KB entry, each the metric reported (GMV ×6, net revenue ×2, gross
  margin % ×1); the 3 "Total sales (order count)" reports, which a containment match paired with GMV, abstain. Rendered
  as **Rule out first** between the bottom line and the recommended actions — web, export and CLI. Live on a scratch
  stack (isolated stores, no model call): the stored GMV report (−€23,173 MoM) lists two deflation causes with fixes.
- **Existing playbooks receive the 486 checks** (answer 7). A check carries the KB `cause` and `fix`, fingerprinted only
  when present, so every other play keeps its receipt and version. At startup `top_up_data_quality` adds each check
  whose stable key (its id without the random suffix) was never in the playbook — a key in the version log whose play
  is gone was deleted by a person, and stays deleted — and fills an empty cause or fix on a check already there without
  touching what a person changed; an empty playbook is left to the seed. Measured read-only, the live playbook holds
  392 plays and no check: it receives 486 on its next start. The playbook screen's status change keeps a check's cause
  and fix.
- **Receipts:** `tests/unit/test_ip1_knowledge_resolver.py`, `test_ip1_package_parity.py`, `test_ip1_rule_outs.py`
  (the count-bracket abstention, the deletion guard, the kept fix and the web note
  each broken once to prove a test fails), `web/components/brief/RuleOuts.test.tsx`; the full backend
  suite once on the commit: 10,598 passed, 5 skipped and 2 failed — two import ratchets the change tripped (the top-up
  read the store's private version-log helpers; the export document, platform code, imported the playbook package).
  Fixed before landing with a public `store.ever_saved_ids` and the lead sentence carried in the payload, so every
  surface renders the backend's words. Both ratchets with the rule-out, parity and playbook tests re-ran green (71
  passed), as did the 15 test files that touch the playbook store, the builder, the export document or the CLI with
  the vocabulary ratchet (293 passed); vitest 967 passed.
- **Open:** SQL repair does not read the checks yet (the other half of "data-quality plays the Verifier and SQL
  repair"); the detection queries wait for IP-3's roles; the one wrong name match measured is "investigation job
  failure rate" on the platform's own operations data with no industry known, a report that states no signed move.

**IP-2 · Chosen at install — BUILT 2026-09-17, MERGED #518** with IP-1. Merged over one red check, the user's call:
the Windows "Start, and both servers answer" install step has failed on main since #509 (2026-09-15) with the same
signature, before this work — the servers answer, then `aughor up` stops a few seconds later. Root-caused and fixed in #519: the serving check's `os.kill(pid, 0)` is a Ctrl+C on Windows, which the console host holds and delivers to every process on the console at its next call; it now asks whether the process exited. The answer is one file,
`data/industries.json` (`AUGHOR_INDUSTRIES_FILE` moves it; gitignored), with three writers in one shape: the
installer, `aughor industries`, and Settings → Organization (`GET`/`PUT /org-settings/industries`).
- **What an answer means** (`aughor/packs/industry_choice.py`). No file, or `null`, keeps every shipped industry and
  detects each connection's (answer 1); a skipped question is written as `null` so a re-run does not ask again. A list
  narrows: `metric_kb.load_industry_kbs()` — through which `match_industry`, `industry_id`, `industry_scope`, the
  vocabulary and the recipes all pass — holds only the chosen packages, so an industry text naming another package
  resolves to none, and a read that knows nothing about its connection (`industry_scope` None) sees the chosen
  industries and the shared knowledge, never another industry's (`readable_industries`, used by the playbook read and
  the rule-outs). An empty list keeps only the shared knowledge — a bank installing today is not handed a retailer's
  playbook. An id no package carries is refused on write and ignored, with its name, on read; an unreadable file keeps
  every industry and says why. Written whole and moved into place; re-read when its modification time or size
  changes, so a choice made in Settings reaches a running API (the vocabulary cache keys on it).
- **The installer** (`aughor/installer.py`, still standard-library only). Step 0, after the checkout check and before
  `uv sync`: the six industry packages, read from `packs/*/pack.yaml` without a YAML parser, numbered; the answer
  takes numbers, ids, folder names or package names, Enter for all, `none`. It asks through `/dev/tty` (the console
  on Windows), so it works under `curl | sh`, where stdin is the rest of the script; with no terminal nothing is asked
  and nothing written. `--industries retail,saas` or `AUGHOR_INDUSTRIES` answers ahead; an id no package carries stops
  the install before anything slow, naming the ids that exist. The option is not handed on to `aughor up`.
- **Changing it later.** Settings → Organization gains an Industries section (app scope — the choice is
  deployment-wide): every industry, or only the ticked ones, saved on its own. `aughor industries` lists the packages
  with the current choice and takes the installer's answers. A change drops only the stored business profiles whose
  industry now resolves to a different package (`refresh_profiles_for_choice`): a profile keeps the recipes it
  resolved when built, and re-inferring costs a model call per dataset, so a retail profile is kept when SaaS is
  added. Settings says how many it dropped.
- **Live, 2026-09-17, no model call:** the question through a real pseudo-terminal with stdin a pipe, as under
  `curl | sh` — a wrong answer asked again, `5, saas` recorded as `["retail", "saas"]`; on a scratch stack with isolated
  stores, Settings → Organization saved retail and SaaS (the API read it back, source `settings`), and `aughor
  industries` read the same file with both ticked.
- **Trap:** the test conftest points `AUGHOR_PACKS_DIR` at a copy of the six packages, so every existing installer
  test would reach the question — and a developer running pytest in a terminal would wait on `/dev/tty`. Every
  installer test now starts with no terminal and its own choice file; the question's tests script one.
- **Receipts:** `tests/unit/test_installer.py` (25 new, 73 in all), `tests/unit/test_ip2_industry_choice.py` (14),
  `web/components/OrgIndustriesSection.test.tsx` (3); `api.gen.ts` regenerated for the two routes; the full backend
  suite once on the commit: 10,639 passed, 5 skipped, none failed; vitest 970 passed.
- **Trap, measured on PR #518's first CI run:** GitHub's Windows runner starts each step with a console but no window.
  `CONIN$` opens there, and the question waited for a key nobody could press — both Windows install jobs sat in
  `install.cmd --no-start` for 20 minutes, where the last green run took two (macOS and Linux have no terminal to
  open, and passed). The question is now asked only where a person can answer: never when `CI` or `TF_BUILD` is set,
  and on Windows only in a console with a window (`GetConsoleWindow`). An unattended run asks nothing and records
  nothing, which keeps every industry.
- **Open:** a person answering in a Windows console is untested here (no Windows machine; CI now skips the question
  by design); the profile inference prompt does not name the chosen industries — the narrowing is at resolution,
  deterministic, and a prompt change waits for a measured reason.

**IP-3 · The generator: gates 3 and 4 as code, airline as the reference — BUILT 2026-09-17, MERGED #519** (squash
`21a4484f`, with the Windows install fix; all 14 checks green, both Windows install jobs included).

The anatomy a package declares with `anatomy: 1`:
- role attributes, named in expressions as `{{role.<role>.<attribute>}}`;
- metrics with a `unit` and a `sane_range`: a min, a max, a basis (the population and period) and sources;
- `sources.yaml`: each source's publisher, url, published and retrieved dates, and each figure with the words it
  was published in;
- plays with an id, a kind (diagnostic, data_quality, practice) and, for data-quality plays, a detection;
- goldens on a named dataset: the metric, a filter, the published value, its tolerance and its source;
- `datasets/*.yaml`, the one place a package names tables: the url, size, SHA-256, load statements, a binding from
  role attributes to columns, and the metrics the dataset measures.

The loader reads all of it as UTF-8 and turns a malformed file into a `PacksError` — a pydantic error from a metric
or ontology file used to escape every caller, the roster route included.

- **Gate 3, the static gate** (`aughor/packs/gate3.py`; `aughor packs check`; `validate_pack` for an anatomy
  package). It checks: schema, sources, a sourced band for every metric, roles not tables, no alias collision,
  bound plays, goldens, datasets and ontology references. For roles not tables, a formula, filter or detection may
  name only role attributes and SQL words; `FROM`, `JOIN`, `SELECT` and `;` are refused. Each rule is proven by a
  planted violation, and every shipped anatomy package passes (the population is read from `packs/`).
- **Gate 4, measured with no model** (`aughor/packs/gate4.py`; `aughor packs measure [--download] [--write]`).
  - The dataset comes from a cache outside the repository; it is downloaded only on request and refused when its
    size or SHA-256 differs from the package's.
  - The load statements build a DuckDB database. Each formula is compiled through the binding into one SELECT, and
    no model writes it.
  - It checks every recipe against its sane range and every golden against its published figure, and runs every
    detection. Claims are tiered by the same model-free build and measurements a connection gets
    (`extract_structural_ontology`, verified joins, cardinality, lifecycles, `apply_core_claims`).
  - Findings: a recipe out of range, a golden that doesn't reproduce, a detection that can't run, a claim measured
    false.
  - The report is stored as `measurements/<dataset>.json`, keyed to the package's fingerprint, and CI fails a stale
    or failing receipt.
- **Airline, the reference package.** `industry.json` and `kb/` are unchanged, as IP-1 moved them. The package adds:
  - four sources: BTS's January and full-year 2019 Air Travel Consumer Reports, its delay-cause definitions, and
    the on-time file, every figure quoted;
  - a flight role with ten attributes;
  - three metrics with sourced bands: on-time arrival rate, cancellation rate, completion factor;
  - an ontology: flight, carrier, airport and aircraft, three links, and the flight lifecycle;
  - eight bound plays, three of them data-quality plays with detections;
  - questions;
  - 14 goldens: the figures BTS published for January 2019;
  - the dataset: BTS Marketing Carrier On-Time Performance, January 2019.
- **Measured on the real file** (the user approved the download: 34,217,271 bytes, SHA-256 `c8cc2c6e…d501b`,
  638,649 flights, 10 carrier networks):
  - Recipes: on time 78.37%, cancelled 3.06%, completion factor 96.94%, each inside its band.
  - Goldens: all 14 reproduce within one-decimal rounding — 78.4% on time and 3.1% cancelled overall, and six
    carriers' on-time and six carriers' cancellation rates.
  - The published on-time rate counts cancelled and diverted flights as not on time. The release does not say so,
    but only that reading reproduces 78.4%; over operated flights the rate would be 81.03%.
  - Detections: 21,000 cancelled or diverted flights, which a wrong denominator would drop; 0 cancellations
    without a reason; 0 late flags on flights that never arrived.
  - Claims: 6 measured-true (four objects; flight to carrier and flight to aircraft, both measured N:1) and 2
    expected — no flight-to-airport join is inferred (two keys point at one table), and no lifecycle is read.
- **Found on the way, each its own task.**
  - The profiler's sampled queries break on DuckDB tables over 500,000 rows. The SQL transpile moves `USING SAMPLE`
    after `LIMIT`, so those tables get no column values and no lifecycle; that is why airline's lifecycle claim is
    unmeasured.
  - The sane-range parser misreads shipped ranges: airline's "ratio 0..1 (0..100%)" is read as 0..100, so an
    impossible 1.4 passes.
- **Receipts:** `tests/unit/test_ip3_gate3.py` (38) and `test_ip3_gate4.py` (10: each failure planted on a 100-flight
  file in BTS's layout, with no download, plus the committed receipt held to the package); the full backend suite
  once on the branch: 10,692 passed, 5 skipped and 2 failed — two ratchets gate 4 tripped (a fingerprint function
  not in the freshness registry; a lowercase `information_schema`). Fixed by registering the receipt's fingerprint
  as a staleness fingerprint and reading DuckDB's own table list; both ratchets, the IP-3 tests and the boundary
  and contract suites re-ran green (94 passed).
- **Open:**
  - More metrics. Load factor needs T-100 data, a separate download to approve. Yield, RASM/CASM and ancillary
    revenue need revenue sources. Utilization, stage length, diversions and delay-cause shares need verified bands.
  - The runtime still reads `industry.json` and `kb/`: pack plays are not seeded into the playbook store, and
    `kb/` detection SQL still names example tables.
  - Gate 5, the with-and-without comparison, spends model calls and waits for the user's go.
  - Gate 6 (a person's review, draft → active) — enforced by IP-4.
  - Authoring the next package (gates 1–2 for IP-4) is still by hand.

**IP-4 · The tiers — ✅ MERGED #520** (squash `7e13f64e`, 2026-09-17; `84524f75` gate 6, `57447363` banking).
The user: *"lets start ip-4"*.

⚠️ **This entry read "STARTED … local, nothing pushed" for two days after it merged, in three places at once**
(here, §3.17's header and §5's band), and a plan-of-record read on 2026-09-19 reported Arc IP as unfinished because
of it. The ledger's own standing lesson, a fourth time: *a struck-through debt list stays honest because striking it
is a deliberate act; a prose claim inside a section rots silently, because nothing forces anyone to look at it
again.* 🔑 The cheap check that would have caught it is one command — `git log main --oneline | grep IP-4` — and it
belongs in any read of this document that a decision hangs on.

- **Gate 6 enforced first.** Every knowledge package said `status: draft` and was read anyway, so a package the
  generator drafts would have reached every agent on the next restart before anyone reviewed it. Measured by a code
  survey: its industry offered at install and matched, its checks topped into the playbook, its example SQL steering
  the profiler.
  - The resolver and the installer's industry list read only **active** packages. A draft awaits a person's review;
    a deprecated package is retired.
  - The eleven packages that were already read are marked active and read exactly as before: the IP-1 parity tests
    pass unchanged.
  - Active never makes a knowledge package steer. `PackManifest.steers` gates `active_packs()` (disclosure,
    steering, bound-pack claims, the agent proposer's catalogue) and routing; `read_pack` answers that a knowledge
    package reaches the agents as reference.
  - A review does not stale a measurement: the receipt's fingerprint leaves pack.yaml's `status:` line out.
    Airline was re-measured on the cached BTS file with identical results.
  - Receipts: `tests/unit/test_ip4_release_gate.py` and the draft cases in the resolver and installer tests. Five
    guards were each broken once, and each was caught.
- **Banking & lending — gates 1 to 4, a draft** (`packs/banking`; dossier
  `docs/INDUSTRY_DOSSIER_BANKING_2026-09-17.md`).
  - **Data.** The FDIC's per-institution financials for June 30, 2025, from the BankFind Suite API: the Quarterly
    Banking Profile's 4,421 insured Call Report filers, 2,938,692 bytes, SHA-256 `2e7f6707…564c`. The user approved
    the one download. The FFIEC's bulk Call Reports have no stable URL (a form postback).
  - **Package.** One role, `financial_period`. Twelve metrics, each a sum over entities, then a division — the
    FDIC's weighted average — with a quarter's income annualized. Bands run from the lowest to the highest rate the
    FDIC published for its asset concentration and size groups in the second quarters of 2025 and 2026. Also
    8 bound plays (4 data-quality with detections), an ontology, questions, and 75 quoted figures.
  - **Measured, no model:**
    - every recipe inside its band;
    - **51 of 51 goldens** reproduce the FDIC's published figure within its rounding — 45 as the Q2 2026 profile
      restates them (return on assets, net charge-offs, the equity capital ratio; all institutions and 14 groups),
      and 6 all-institution figures as first published;
    - detections 1 / 0 / 6 / 1,036;
    - claims 2 measured-true, 12 expected, none false.
  - **Found on the way.** The FDIC amends old quarters: the API's snapshot reproduces the restated figures, not the
    originals. Return on equity, efficiency and coverage have no golden, because the amendments moved them past the
    rounding of their only publication. The data settled one definition: the equity ratio uses the bank's own equity.
  - **Receipts:** `tests/unit/test_ip4_banking_package.py` — four banks in the API's layout, every value worked by
    hand, no download. An average of the banks' margins, and a quarter left unannualized, each fail; the committed
    receipt holds the 51 goldens.
- **Open:**
  - ✅ **The runtime reads a package's anatomy — plays and metric recipes MERGED #534** (`06d9d296`, 2026-09-21).
    An active package's declared plays are seeded into the playbook store, where the retriever, the Verifier's
    rule-outs and the prompt already read (`seed_from_packs`, sourced through `knowledge_index()`, so gate 6 holds
    by construction: banking, `draft`, contributes nothing). Its typed metric recipes reach the explorer's prompt
    ahead of `industry.json`'s prose, and `resolve_recipes` and `metric_vocabulary` read the same merged view —
    which stopped `match_metric` answering "completion factor" with the **Cancellation Rate** recipe on airline.
    ⏳ A package's **questions** are not named by #534 and were not re-measured here. Banking still carries no
    `industry.json` or `kb/`, but it has `metrics/` and `playbooks/` — so activating it now changes what an agent
    reads, through the seam above, where before #534 it would have changed nothing.
  - **Industry matching.** `_UNCURATED_INDUSTRY_TERMS` lists banking's words; they come out at activation, and a
    shipped industry that is not chosen must keep blocking a generic match (measured: "Retail Banking" would match
    retail again).
  - **Loan-level lending**: delinquency buckets, roll rates, vintages, approval rates.
  - **Payments & fintech, then insurance.**
  - **Gate 5**: not needed for banking — gate 4 is unambiguous (answer 8).
  - **Gate 6**: the user's review.
  - **Found by the survey:** promotion rewrites pack.yaml without its comments (its own task).
  - ✅ **A published figure is reported from the receipt that measured it.** `check_expectation` skipped every
    expectation key it did not know, so IP-3's goldens scored as passing wherever the evaluate and status doors ran
    them — airline 14 of 14, banking 51 of 51, with nothing computed and a planner pass spent on each. The checker
    now refuses a golden it cannot judge (and any unknown key, by name), and the runner reads what
    `aughor packs measure` wrote in `measurements/<dataset>.json`: a receipt that is missing, that describes an
    older package, or that says a figure did not reproduce is reported as that, never as a pass. The door
    downloads nothing, builds nothing and calls no model.
  - ✅ **A pack's claims can no longer reach a model through the explorer.** ON-7b gave the ontology explorer a
    catalogue that rendered every claim — expectations included, from any pack a person had measured against the
    connection — while `ontology_map.py` and `CoreClaim` both said claims are never rendered, and ON-0a's rule is
    "nothing from the map reaches a prompt block except through the same verified tier" (an entry measuring FALSE
    is "rendered nowhere"). The catalogue now renders a claim only when a pack DEPLOYED on the connection (active
    and bound) measured it TRUE; the measure door still takes any pack id, because reviewing a package against
    your own data is what gate 6 asks for, and its answer says whether the pack is deployed. The two comments say
    that now. The reach ratchet did not cover the explorer's prompt at all — that is why the block landed
    unnoticed — so `explorer_catalogue` is one of its blocks, with its measured reach recorded (49 fields).

**The package.** A pack — the plane that already has `extends`, a draft → active gate, validation, evals, bindings and
ontology claims — carrying one industry: `pack.yaml` (id, industry id, aliases, extends), `ontology.yaml` (claims),
`metrics/*.yaml` (formula, grain, sane range with its source, anti-patterns), `playbooks/*.yaml` (diagnostic,
data-quality and practice plays, each bound to a metric it declares), `kb/*.json` (causes, detection SQL, fixes),
`questions.yaml`, `evals/*.yaml` (goldens on a named public dataset) and `sources.yaml`.
**Laws:** data, not code; everything a claim until measured; no table names; never the organisation's ontology (§6
item 20); a sane range without a source fails the gate.
**Layers:** functions (finance, marketing, product, customer, risk-and-fraud) apply to any industry. Bases implement a
KPI shape once — a ratio of sums, a rate over time-weighted exposure, ageing and roll rates, churn with a declared
unit, decision rates, clocks with a start, a stop and a tail, completion of immature periods, results with and without
extreme events, rates by count or by value — and every money measure states what it includes (DoorDash's order value
includes tips; Uber's bookings exclude them). Industries extend bases; a company extends its industry, by people.

**How the agents read a package.** Every read is scoped to the connection's industry — IP-0's rule, extended to the
deep KB and the recipes. Diagnostic plays feed the Explorer's angles and the Analyst's synthesis; data-quality plays
the Verifier and SQL repair; practice plays the recommendations. Reference is not steering: recipes, plays and claims
are read without a binding, while a persona and role-bound recipes keep the pinned-binding gate. **The Briefer reads
the recipes** — sane ranges and anti-patterns on the numbers that moved (§6 item 21, answer 5). **The Curator measures
a package's ontology claims on every connection of its industry** into measured-true, measured-false and expected
(answer 6); nothing unmeasured reaches a prompt.

**Chosen at install.** The question sits inside the one-line install of #501 — nothing typed before it or after — and
before the slow steps. `curl | sh` leaves stdin at the end of the script, so the answer comes from `/dev/tty` (the
console on Windows); with no terminal nothing is asked, and scripts pass `--industries` or `AUGHOR_INDUSTRIES`. The
installer stays standard-library and writes one small file the API reads. **Skipping keeps every shipped package
available and detects the industry per connection** (answer 1); a pick narrows what the profile may choose from. It
changes later in Settings → Organization or with `aughor industries`. **Packages live in the repo** (answer 2).

**How a package is made — six gates, in order.** (1) A cited dossier. (2) A drafted package: authoring tokens, no
Aughor model. (3) The static gate, in CI: schema, a source per sane range, roles not tables, no alias collision, every
play bound. (4) Measured on public data, no model: every recipe inside its sane range, every claim tiered, every
detection query run; where no realistic public data exists, reproduce the regulator's published figures from the
regulator's own data and test lifecycles on a synthetic generator. (5) Ablation with and without the package — model
calls, run for the reference package and afterwards only where gate 4 is ambiguous (answer 8). (6) A person's review:
draft → active.

**Waves.**
- **IP-0** an honest playbook — ✅ BUILT (above).
- **IP-1 the package seam.** Industry ids on packs; packs load plays and KB entries through one resolver that replaces
  the four hard-coded `data/kb` loaders; the six industries and the functions move into packages unchanged;
  data-quality plays reach the Verifier. Only then do existing playbooks receive the 486 plays (answer 7: not yet).
  ✅ BUILT 2026-09-17 (above): the Verifier's rule-outs on deep reports, then the top-up.
- **IP-2 chosen at install**, as above. ✅ BUILT 2026-09-17 (above).
- **IP-3 the generator.** Gates 3 and 4 as code, and airline brought to the full anatomy as the reference package.
  ✅ MERGED #519 (above): 14 of 14 published BTS figures reproduced with no model.
- **IP-4 the tiers.** ✅ MERGED #520, squash `7e13f64e` (above): gate 6 enforced; banking & lending through gates
  1–4, 51 of 51 FDIC figures reproduced with no model.
  🔴 **Shipped and INERT, which is gate 6 working rather than a defect.** `packs/banking/pack.yaml` carries
  `status: draft`, and a draft is read by nobody — not the resolver, not the installer's industry list. Measured
  2026-09-19 on `c7085899`: four other packages sit in the same state (`core-ecommerce`, `customer-analytics`,
  `fashion-ecommerce`, `supply-chain`). **The next act on this wave is a person's review, not a build** — and that
  is the gate doing exactly what it was built for, one wave after being built.
  - **Tier 1:** banking & lending **first** (answer 3, the builder's pick: 26 of 27, nine of ten vendor catalogues,
    and FFIEC Call Reports that reconcile to the FDIC's published totals), then payments & fintech (it reuses
    banking's parties, accounts and transactions), then insurance; the finance and risk-and-fraud functions alongside.
  - **Tier 2:** healthcare, payer module first (moved from tier 1 by answer 4), pharma after it, CPG, travel &
    hospitality, energy & utilities, telecommunications.
  - **Tier 3,** when a customer asks: public sector, education, capital markets & wealth, media with advertising, oil &
    gas, automotive, restaurants. **Tier 4,** drafted from a standard on demand: real estate, construction,
    agriculture, gaming, nonprofit, professional services.

**Falsifier.** If gate 5 on the reference package shows no lift or a regression, package prompt blocks are retired and
a package's value is confined to the guards and the compiled path — ON-0's rule (§3.15), applied to packages.

**Not this:** a prose block per industry; a reference model adopted wholesale (FIBO, FHIR, ACORD and IEC CIM are
quarries, as §3.15 ON-0a says); a registry or any second distribution channel; a package or an agent that writes the
organisation's ontology; a table name inside a package.


### 3.18 · Arc HB — the hub: people still come to the platform, and the platform also receives data and exports intelligence (drafted 2026-09-16 at the user's direction — §6 item 24; the shape decided in conversation 2026-09-15; **ADOPTED 2026-09-16** — item 24 (a), (b) and (d) stamped on the user's *"Lets take the logical next step.. go.."*; **HB-1 FIRST SLICE STARTED** the same day)

> **Origin.** The user, 2026-09-15, after asking how a CEO, a supply-chain head, a pricing analyst and a finance
> controller should each benefit: *"think even bigger.. beyond roles.. the entire platform is a collection of moving
> parts. Everything is modular, everything can be Agent driven and everything is composable and communications can
> happen across platform such as Slack Gmail confluence jira etc.. imagine that it's the biggest airport and hub for
> company functions where informations flows from & to.."* Then, in order: *"I like the airport analogy.. but let's not
> change the nomenclature that we already have"*; *"I want to know the cost of doing so. Cost not in terms of tokens
> but the value that we were delivering earlier and the value that we will end up delivering"*; the four people *"are
> just examples. The idea is to have features that will serve for every layer in the organisation"*; *"the layer
> structure is very rigid.. one person cannot be a function head and an operator by your definition. I rather like the
> approach that Databricks has"* — their workspace access-control page: persona groups, permission levels per object,
> custom permissions on top, additive, a service principal as owner; *"I like the ideas of personas. The
> organisation's functions such as supply chain finance pricing can be achieved through creating groups of users within
> the platform"*; and the definition, confirmed: *"the reason why people should come to the platform remain but it will
> also act as a hub that receives data and exports information, intelligence, analysis, etc."* Companion page (the
> user's, private): https://claude.ai/artifact/Sa9iBaxHPnfPaGKgUKp6Na.

**What the hub is — and the one word that keeps it from becoming a pipe.** Every reason to open the platform stays:
ask, run your own SQL, read the Briefing, open an object, approve a change. The hub is where those things now also
*leave from* and *return to*. It **receives** data (the warehouse, read-only), documents, definitions, ticket state and
what people say in the channels they already use; it **exports** findings, analyses, Briefings and proposals — each with
its receipt, to the group that watches the thing it is about, gated harder than the screen. What leaves is
*information the platform has measured*, never the data: the warehouse stays where it is and the hub sends the finding
about it. The airport is an analogy and nothing more (the user's rule): an airport owns no aircraft and no cities — it
owns the map (the ontology), the tower (governance and Spotlight), customs (the guards, PII, receipts, KI's review
lane) and the schedule (automations). The product's words do not change: automation, notification, monitor, Briefing,
subscription, grant, group, connection, approval, action.

**The premise, measured on main `61cba06a` (2026-09-15) — most of the airport is standing; the traffic system is
not.**
- **Receives:** seven warehouse kinds, uploads and Sheets; PDFs and scans (§3.13); Confluence and Notion definitions
  through KI-3's review lane; a Slack @mention (Socket Mode); one inbound hook per automation
  (`POST /hooks/{automation_id}`, DS-17); an allowlisted MCP server's tools (`aughor/mcpservers/` — a write needs OUR
  grant and a changed declaration revokes it, `call.py:74`, `discover.py:85`).
- **Exports:** Slack (`slack_post`), webhook and Jira (`notifications/models.py:22`), the MCP server (18 tools plus
  automations), proposals into approvals. **No email in either direction.**
- **The schedule:** five triggers — `schedule · metric · source_change · entity_appears · webhook`
  (`automations/models.py:75`) — and twelve effect kinds (`:263`); an automation runs as a named agent (VA-9b). A
  promise or a finding is not a trigger. Packs carry no automations.
- **Nothing links a thread, a ticket or an email to an ontology object** (zero files); findings, notes and declared
  actions attach to an object (ON-3) and nothing else does.
- **Nothing routes:** a `BriefSubscription` has a connection and a cadence, no subject and no reader
  (`briefing/models.py:19`); a monitor has a channel; the Briefing's lead is ranked by ONE `BusinessProfile`'s north
  stars (`knowledge/triage.py:402`) and its narrator addresses the organisation (`knowledge/briefing.py:358`) — the
  reader is the company everywhere.
- **Access:** `Principal` is a user id and an org id (`security/authz.py:39`); **no groups anywhere**; three roles × ten
  permissions with an endpoint→permission table (`rbac/policy.py`) and capability ceilings;
  `metastore.Grant(principal, securable, privilege)` holds one privilege, `USAGE`, on one securable kind,
  workspace→catalog (`metastore/models.py:124`); securable strings are `catalog | schema | table | artifact` with
  governed tags whose only load-bearing keys are `tier` and `pii` (`govern/tags.py:46`); `owner` is free text on
  metrics, processes, rules and agents; `StandingGrant` is a per-action, per-target grant (`actions/grants.py`); row
  filters compile (`sql/rls.py`) and `ROW_POLICIES` ships empty; `RolesPanel.tsx` assigns the three roles.
- **Accuracy at the edge:** a metric's `quality_tests` ("failure = metric flagged unreliable") run through ONE
  on-demand caller (`routers/metrics.py:211`) — a failing tie-out never holds a number out of the Briefing; the
  Briefing re-runs a cited number only when a reader clicks it.
- **Pricing knowledge exists and nothing looks for it:** price realisation and discount depth in the deep KB
  (`data/kb/fin_revenue_level_2.json`, `ec_orders_revenue_level_2.json`), no pricing angle in the Explorer's defaults
  (`explorer/agent.py:2247`), no pricing function in §3.17.

**The cost, in value — the user's question, answered before anything is built.** Today's value is *pull*: a person
asks and gets a right answer with its receipt beside it (Olist: framed 8/12 against raw 3/12; the guards 100% safe).
The hub's value is *push and return*, and its price is paid in the currency the platform earns today — trust and
attention:
- A wrong push is negative value, not zero: a wrong tile waits on a screen; a wrong finding lands in `#ops` with a
  ticket proposed.
- Fan-out amplifies every error, and the receipt is one link away for a reader who did not ask — so the departure gate
  must be stricter than the screen, and the hub will hold back things the Briefing shows.
- The hub cannot close the last mile alone: agents propose, people ratify. Said plainly it is a strength; unsaid it is
  a broken promise.
- An inbound channel is an attack surface (email is untrusted text into the agent) and customs is human labour (KI's
  review lane is a person approving).
- Value becomes contingent on other systems' uptime and other people's approvals — the email channel has waited on one
  Google OAuth client since VA-11.
- Push is worth its uptime: a hub asleep on a laptop delivers nothing. Arc MT was dropped because hosting does not work
  well enough (§6 item 17); this arc does not reverse that — it exports only from where the platform actually runs.
- The value shows at organisational scale, across several readers in several channels — a J-curve; **where the
  platform runs today, one analyst and local, the hub's value is unobservable**, and §7's failure (tested, not
  leveraged) becomes MORE likely with every channel built ahead of traffic.
- Every channel built is an ontology wave not built; channels are commodity (Zapier, n8n, Slack apps, Atlassian's own
  MCP server), the ontology→agent loop is not (§0).

What the hub adds that pull cannot: **outcomes** (nothing today records whether a finding was worth acting on — MI's
graded ledger gets its missing ground truth), **context from people** (the warehouse does not hold "carrier X was on
strike last week"; caught in Slack and filed on the promise, it makes the core answer better), **reach** (the same
measured correctness for people who never open the app) and **memory** ("why did we decide that in March?" with a
chain).

**Five laws, each an extension of one the platform already keeps.** (1) *The hub owns meaning, not data or work* —
the warehouse stays read-only, nothing is copied in, Slack, Jira and email stay where the work happens. (2) *Every
automation declares its plan* — its trigger, its steps, its destinations, its cap; it runs as a named agent under a
grant; it appears on one map. (3) *Customs both ways* — in: measured before believed (KI's lane, ON's claims); out:
nothing leaves without a grant, a PII scrub and a receipt attached. (4) *Quiet by default* — the hub speaks by schedule
and by exception; a run that would spend the model says so before it runs. (5) *Everything lands on the map* — a
message, a ticket, a decision or an answer that passed through is filed against the object it is about.

**Groups and grants — the answer to "every layer", with no layer.** Two kinds of group, both plain groups; a person is
the union of their groups' defaults and their own grants, clearances the one AND; additive, no deny — the Databricks
shape the user chose, on our own seam:
- **Persona groups** are shipped by the platform and carry a default **level per securable kind** instead of one
  uniform verb. The ladder is **View < Subscribe / Run < Edit < Manage < Own**; today's `viewer` / `analyst` (Editor) /
  `owner` become the first three persona groups with their stored values unchanged, and an organisation may add a
  persona (a Steward who manages definitions and not connections) as data. "Analyst" stays the agent's name.
- **Function groups** are the organisation's — supply chain, finance, pricing — created by people or shipped by a pack,
  and carry what a persona cannot: **members** (people AND agents: the supply-chain group's Watcher inherits the group's
  grants and speaks in its channel — Databricks' service principal, in our terms); **a channel** (`#ops`, a Jira
  project, later an email list) where a departure for that function lands; **grants by tag** (`Subscribe` on anything
  tagged `domain=supply-chain`, `Own` on the dispatch process), so a promise declared next month is covered the day it
  is tagged — which makes `domain` a grant-bearing tag beside `tier` and `pii`, a small explicit change and §6 item
  24(b); **row policies keyed by group** (finance reads cost columns, ops does not — the compiler exists, the table is
  keyed by role and empty); **a pack**.
- **Securables** grow to the ontology's things and artifacts the way catalogs and artifacts already have strings:
  `metric:` `promise:` `process:` `rule:` `domain:` `automation:` `agent:` `canvas:`. **Inheritance** follows meaning,
  not storage: a grant on a domain flows to its objects, on a process to its promises; an explicit grant on a child
  adds. **Ownership** becomes a principal — a person, a group or an agent — which is what makes routing deterministic: a
  breach goes to the promise's owner and its subscribers, and no model decides who gets what. **One resolver** —
  `may(principal, level, securable)` with an `explain` that names the grants — replaces the four separate checks (tier,
  role, endpoint policy, clearance) at the existing gate sites; the clearance decision already names what blocked, and
  the union must name what granted.
- **Adapted, not copied:** their six personas → the organisation's own functions plus the ladder we have; Dev/UAT/Prod
  → the propose/approve lifecycle (a draft metric IS Dev; §6 item 9's two recorded acts are their segregation of duty);
  folders → the ontology hierarchy; Terraform → grants as pack data and the organisation's people-edited overrides
  tree. Our one addition: a group has a channel, because we push and they do not.
- **With identity off** `resolve_roles` returns owner and everything is allowed — enforcement is inert where the
  platform runs today, exactly as RBAC's was. The **routing half** (groups, membership, a channel, `Subscribe` and
  `Own`) has value with identity off because it decides where a breach *goes*, so it is built first; enforcement rides
  the same table and switches on with OIDC, whose groups claim maps onto `group:` principals.

**The departure gate and probation — what is done about accuracy.** Nothing leaves the screen that the screen would
not show, and less: (1) **re-measured at send time** — the number that leaves is re-executed at departure, never a
cached figure (the Briefing's "show the receipt" re-run, made the law); (2) **definition-gated** — a number leaves only
citing a governed metric, a declared promise or a declared rule, never an inferred definition (the Briefing's trust
gate, extended from metrics to promises and rules); (3) **tie-out gated** — `validate_metric` runs in the gate, not on
a click; (4) **freshness-gated**, and the message says *as of*; (5) **claim-type gated** — a descriptive fact may
leave, a causal claim only with its falsifier's verdict (`agent/claim_type.py`), a forecast never (no forecaster
exists); (6) **disagreement holds** — where the ambiguity probe finds divergent readings a departure has no asker, so
it asks the OWNER and sends nothing until answered; (7) **the noise band** of the triage's change term, never the same
finding twice, monitors' anti-flap; (8) **the receipt travels** — source, definition version, as-of, guards applied and
a link to the chain on every message. **Probation:** a new automation's departures go only to the person who declared
it, who marks each right or wrong through the feedback plane (accept · correct · reject); it graduates to its
subscribers at a measured precision and the ratchet holds it there — a change that lowers a departure kind's precision
cannot ship. This is MI-1's graded ledger with an outcome column, the hub's contribution to §3.9. **Corrections
return:** "wrong" in the thread is feedback into the closed loop and the ambiguity ledger (the mechanism measured
+0.70 on a repeat set).

**Context from many sources — stored where it already belongs, ranked by no model.** No ninth store (§8): definitions
through the review lane into the glossary and the metrics catalog; observations as notes under `agent_notes`'
blast-radius law; verified statements in the claims ledger; documents in the documents plane; the manifest is links,
not copies. The one new thing is a **provenance envelope** on every piece — source kind · author (person, model,
system) · scope (object → connection → domain → organisation → industry) · observed-at with a validity window ·
verification tier · blast radius — completing PX-5's substrate (source asset, author, verification outranks
authority). **Ranking is deterministic on three axes and shown in the receipt:** *authority* — measured against the
data > approved by its owner > declared by a person > mined from a document and reviewed > said in a conversation > a
model's inference (the metric precedence catalog > north-star > verified > unverified, generalised); *scope* — this
object > this connection > this domain > the organisation > the industry pack (the glossary's layers, the `org/domain`
key, IP-0's industry scope); *recency per kind, never one global score* — a definition's current approved version wins
regardless of age, an observation decays and expires unless re-affirmed, a measurement carries the data's own "as of"
and the freshest wins. **Conflicts:** same tier — surface it, ask once, remember (the ambiguity ledger); different
tiers — the higher wins and the lower is kept as a flag in the receipt. Every block carries its stamp
(`[measured 2026-09-14, this connection]`, `[said by A. in #ops, 3 days ago, unverified]`); the ranker fills the Agent
Context budget by authority × scope × recency and says what it dropped. **The measurement decides it:** the only
ablation of injected context (R4, 2026-06-21) was a regression and ON-0 lifted nothing until the framing did, so each
new source kind enters the prompt under its own harness arm and stays only with measured lift, per kind and per tier;
a source that does not lift is stored and shown, not injected. What a person said in Slack is a payload under §6.4;
the note derived from it, once accepted, is a work artifact; PII scrub at intake; the organisation's ontology stays
human-edit (§6 item 20) — conversation-derived context is a proposal or a column-local note, never a silent write.

**Waves — each built on what stands, each with a receipt and a falsifier.**
- **HB-0 · measure** — ✅ DONE 2026-09-15 (the premise above; the value ledger; the companion page). Re-measure before
  each wave: a catalogue has a timestamp.
- **HB-1 · groups and grants, the routing half.** Groups and membership in the RBAC store; `group:` and `agent:`
  principals; a group's channel; securable strings for the ontology's things; `Subscribe` and `Own` in the grant store;
  owner as a principal on metrics, processes, promises and rules (a migration from the free-text field); `domain`
  grant-bearing (24 b); `BriefSubscription` gains a subject and a reader; `RolesPanel.tsx` grows into groups, members
  and grants-by-securable. *Receipt:* a person in two function groups receives, through each group's channel, exactly
  what each group subscribes to, and `explain` names the grant. *Falsifier:* if routing by ownership sends a finding to
  the wrong group on a measured set, the map is wrong before the code is.
  > **First slice BUILT 2026-09-16.** In code the personas spell themselves **built-in groups** — the vocabulary
  > ratchet retired `persona` (one of five words for a custom agent) and the guard is right: the concept IS the three
  > roles wearing a level per securable kind (`rbac/levels.py`), so the code says so. What stands: `groups` +
  > `group_members` in the SAME `rbac.db` (people AND agents as principal strings, a channel as an Action Hub trigger
  > id); the ladder `view < subscribe/run < edit < manage < own`, additive, fail-closed on unknown words; the
  > ontology's securable strings beside the catalog ones; `domain` grant-bearing (`GRANT_BEARING_KEYS`, tags stay
  > human-set); level grants riding the metastore `grants` table beside USAGE; ONE resolver `may()` whose explain
  > names what granted, walking a meaning chain the CALLER presents (parents + the domain tag — the module stays pure
  > over stores it does not own); `route()` = owner + Subscribe-or-higher holders, each group through its channel,
  > deduplicated; owner-as-principal by INTERPRETATION (`owner_principal` reads `group:finance` as routable and
  > leaves "Ana (logistics)" the display text it always was — no YAML rewrite; the overrides tree stays human-edit,
  > §6 item 20); `BriefSubscription.subject/reader` additive; doors `/groups`, `/access/grants`, `/access/explain`,
  > `/access/route`, gated at `admin.manage_roles` for mutations and the people-naming lists, receipts at the open
  > floor. The receipt holds as a test (two groups, two channels, one person in both — each channel gets exactly its
  > subscriptions, the why names the grant); the wave's live receipt still wants real traffic, which is HB-3's
  > breach. **Open in the wave:** the `RolesPanel.tsx` growth shipped as a first pass (groups, members, grants);
  > enforcement at the four gate sites stays OFF by design (the routing half; rides identity).
- **HB-2 · the departure gate and probation**, as above. *Receipt:* a Briefing tile the screen shows is held at
  departure by a failing tie-out, with the reason recorded; an automation on probation reaches only its declarer until
  its measured precision graduates it. *Falsifier:* a departure precision baseline that a later change lowers cannot
  ship — the ratchet.
  > **First slice BUILT 2026-09-16** — same day as the wave's live motivating receipt: theLook's brief departed to
  > #aughor_canvas prefixed "NOT reliable" (a trust reframe warning readers off numbers a channel had already been
  > handed). What stands: `govern/departure.py` — content customs beside `govern/outbound`'s transport customs — wired
  > into the two UNATTENDED transports (`_dispatch_slack_post`, `_dispatch_notify`; the inbox's accepted-proposal send
  > stays ungated by design — a person reviewed that text and pressed send). Three checks, every decision in the
  > departures ledger (`data/departures.db`, hermetically registered same-commit): **trust** — the reframe banner is
  > composed from ONE constant (`TRUST_BANNER`) and detected at the gate, so the flagged brief the screen shows is
  > held from the channel; **tie-out** — `validate_metric` runs AT THE GATE on governed metrics the departing text
  > asserts (`asserted_governed_metrics`, the drift guard's own matcher made public), fail ⇒ held, error ⇒ recorded
  > "unavailable" and departed (an infrastructure hiccup is not a failing number); **probation** — `declared_by` +
  > `probation` on the automation (migration 8; create doors set them; the store preserves them across authoring
  > saves, first-writer-wins on the declarer), a probation send lands on the declarer's ledger queue instead of the
  > channel, verdicts (accept·correct·reject, forwarded to the feedback plane when investigation-linked) graduate it
  > at measured precision (≥80% over ≥5 marked, plus a manual door) — inert with identity off exactly as HB-1's
  > enforcement, since `current_user_id()` is then empty and there is nobody to address the review to. An accuracy
  > hold outranks probation. `held` joined the step-outcome vocabulary (terminal, never retried); the investigate
  > step now publishes `confidence` beside `summary` (measured: NOTHING of the synthesis but the summary text used to
  > cross into a chain). The ratchet is a labeled corpus (`test_departure_gate_ratchet.py`) with the live incident
  > verbatim as its anchor case — a flipped verdict is red, and relabeling is named in the failure message as
  > defeating the ratchet. Receipt held as tests on real SQL (HB-1's precedent): a governed metric's genuinely
  > failing quality test held the send with the reason recorded, the same send departed once the data was clean, and
  > five accepted marks graduated a probation chain whose next send reached the transport.
  > 🔴 **Found broken on the way: the tie-out plane had never worked.** `validate_metric` — quality_tests' ONLY
  > caller — called `conn.execute(sql)` against the governed `execute(hypothesis_id, sql)` signature, so every
  > quality test errored (reported as "failed"); and the connection layer stringifies cells, so a boolean `False`
  > arrived as `'False'` — truthy — a failing test that could not fail. Both fixed with direct coverage; the gate is
  > the first caller that ever needed the verdict to be right. **Open in the wave:** the other outbound transports
  > (monitor alerts, briefing subscriptions, the human-initiated finding share, agent alerts — `fire_action`'s other
  > callers); gate laws 1 (re-measure at send), 2 (definition-gated beyond metrics), 4 (freshness + as-of), 5
  > (claim-type), 6 (disagreement asks the owner), 7 (noise band — the router's dedupe is the start); the receipt
  > line ON the departing message (law 8 is ledger-side only so far); a departures screen (the doors serve JSON;
  > the runs rail already shows a held step's reason); auto-graduation's outcome window (HB-3's ground).
  > **REMAINDER BUILT 2026-09-17** (the user: *"Go for the HB-2 remainder first"*; branch `claude/hb-2-remainder`).
  > **Every way out asks the gate.** Monitor alerts, scheduled briefings, agent alerts and a person's Share and
  > Execute left ungated before; now every call to a message transport (`fire_action`, `post_as_bot`) asks the
  > gate in the same function or is excused by name with its reason (`UNGATED_BY_DESIGN`: the two inbox accepts —
  > a person reviewed that exact send — and the Action Hub's fixed `[TEST]` payload). Held structurally:
  > `test_departure_every_exit_gated.py` walks the syntax tree of every `aughor/` module, so a send added later
  > that forgets the gate is red, and an exemption whose call site is gone is red too.
  > **The laws, each deterministic and recorded per guard** (`govern/departure.py`; the measurements they read
  > come from `govern/departure_basis.py`, no model anywhere):
  > law 1 re-measures — every magnitude the text states must be in the measurement it departs on (an analysis's
  > kept result rows, a promise's stamp scoped to exactly that promise, a finding's query re-run), re-executed when
  > older than 30 minutes, and a magnitude with no measurement behind it holds; grounding is precision-aware
  > (`numeral_matches_measure`: a number written in full claims its last significant digit — the finding guard's 2%
  > let "99,441" pass as 1.6% from the stamped 101,033 kept lines) · law 2 holds a well-known KPI stated with a
  > number and no approved metric behind it, a draft metric, or an object not declared and measured on the
  > connection; a monitor's or alert rule's own declaration defines what it measured, and a monitor's catalog
  > metric is judged directly (`metric:<name>`) · law 4 holds a governed metric whose data breaches its declared
  > SLA and states the as-of everywhere one is known (no SLA declared → nothing to judge, never an invented bar) ·
  > law 5 lets a causal or associational sentence depart only on the licence its analysis recorded
  > (`agent/claim_type.py`'s CLAIM LICENCE; a recorded adversarial refutation withdraws a causal one) and a
  > forecast never (`sentence_claims`, negation-aware, forecast phrasing wider than the report checks' on purpose)
  > · law 6: an analysis that PAUSED on divergent readings used to starve its send into a skip nobody was told about;
  > the runner now reports the pause, the send is held for the metric's routable owner (`held_owner`) with both
  > readings and their SQL, and `POST /departures/{id}/answer` crystallizes the choice in the ambiguity ledger at
  > user authority, so the next run binds it — asked once · law 7: an unattended automation never sends the same
  > message to the same place twice in 7 days, and a repeat whose every number moved less than 5% is noise; alerts
  > keep their own anti-flap policy, a scheduled briefing speaks by schedule, a person chose · law 8: the receipt
  > (source · definition · as-of · the guards that ran · the ledger row, linked when `AUGHOR_WEB_URL` is set)
  > travels on the Slack post, in the webhook's `context` and on the Jira ticket, and is stored verbatim on the row.
  > A scheduled briefing is judged line by line first: causal-graph relationships never depart, a finding line
  > with an inferred KPI is cut, the rest leave with a "N lines held at departure" section and receipt count.
  > **Live anchor, in the ratchet corpus verbatim:** the 2026-09-16 dispatch watch departed "10,423 of 99,441 order
  > lines (9.35%)"; the promise it was about counted 111,456 lines — 99,441 is Olist's order count (the delivery
  > promise's objects). Law 1 now holds it; the same message with 111,456 departs. **Calibrated before shipping on
  > real traffic:** two real theLook briefing summaries ground every magnitude in their own rows and classify
  > wholly descriptive, so ordinary sends are not held.
  > **The departures screen** — an Agent Ops layer beside the Hub (`DeparturesPanel.tsx`, `lib/departures.ts`):
  > every departure, its state, the reason in a line, and on Review the full record (reasons, each guard's outcome
  > in the order it ran, the message, the receipt it carried or would have); a declarer's accept / needs
  > correction / reject and an owner's reading choice live there; the layer's badge counts what a person owes;
  > a receipt's `?departure=<id>` link opens its row. Share passes its connection and says "Not sent — why";
  > Execute stopped reporting "✓ sent" for a send the gate kept in. Driven live on an isolated scratch stack
  > seeded through the real gate: eight departures, the owner's answer remembered (`GET /learning/resolutions`
  > showed the reading and its SQL at source `user`), the table overflow found and fixed (1,233px in a 1,160px
  > pane). **HB-3 had already taken** auto-graduation's outcome window (the structural unlanded falsifier), so it
  > is not open here. **Still open:** the live drive on the deployment once merged (the Olist watch will HOLD —
  > its literal message states the order count); marking a verdict is not enforced to the addressee while identity
  > is off (HB-1's posture); a deep run records no falsifier SURVIVAL for causal claims beyond its licence;
  > "wrong" said in a Slack thread does not yet return as a correction.
(after HB-2's last blockquote line, before `- **HB-3 · promises and findings as triggers`)
Keep the two-space indent: this is a continuation of HB-2's bullet.
============================================================

  > **A4 · THE IMPOSSIBLE-LAG CAVEAT, AND THEN THE HOLD — BUILT 2026-09-20** (`407f0a4c`, then
  > `7cd717e0`; origin `docs/JEV_ALIGN_STUDY_2026-09-19.md` finding A4 — the frozen-population rule as
  > a standing guard, §3.20). **The live anchor.** LuxExperience declares a refund promise — refund
  > within 10 calendar days of the return arriving — and the platform measured it: **11,648 of 50,048
  > Returns breached, 23.27%**, as of 2025-08-14, `flags: []`. The same stage, ONE LEVEL UP from the
  > promise block, already counted `out_of_order: 4,199` and already said so in its own note:
  > **4,199 Returns were refunded BEFORE they were received.** A negative lag can never exceed the
  > window, so every one of them was counted as KEPT. Without them the rate is **25.41%** — the failure
  > understated by **2.14 points**, in the business's favour, on a number that leaves the building.
  > 🔑 Nothing was hidden. It was computed one level away from the reader, which is the same thing.
  > **The caveat first** (`407f0a4c`). `_flag_out_of_order` puts it on the PROMISE, reusing the `flags`
  > vocabulary that already exists ("never broken", "always broken") rather than inventing a second
  > one — so it rides for free into the panel's red text, the object door's query caveats and the
  > frame's notes. The alternative rate is arithmetic, not a second query, and it is stated only when
  > it is SOUND to state: a **window** promise, never a `deadline` one (where `out_of_order` compares
  > stages the deadline says nothing about, so *"cannot break the promise"* would be a FALSE sentence
  > rather than merely an unhelpful one); counted per the process's own type, so the two counts share a
  > population; and something left once they are removed. When any of those fails the ordering is still
  > flagged, just without a rate — saying less beats saying something derived from the wrong
  > denominator. The departure path was the one surface that dropped it: `Measurement` had no caveat
  > field, so 23.27% departed clean. It now carries `caveats`, filled from the promise's flags on BOTH
  > the ontology and hub-stamp paths (`govern/departure_basis.py`), and `receipt_line` states them
  > **before** the guard list, because a caveat after a row of green ticks reads as a footnote to
  > reassurance.
  > **Then the hold** (`7cd717e0`), **the user's call**, made once A4 showed the caveat travelling and
  > stopping nothing: *a measurement that refutes its own number does not leave.* A ninth guard,
  > **`caveat`**, placed beside `trust` because both are accuracy holds about the FIGURE itself rather
  > than about who may receive it, and reached the same way — from the measurement, never from the
  > text. Which caveats block is `departure_basis._blocking`'s call and not the gate's, so the gate
  > never has to learn a promise's vocabulary. `Measurement.blocking_caveats` is kept separate from
  > `caveats` deliberately: collapsing them turns *"a caveat holds"* into *"every caveat holds"*, and
  > 🔑 **a gate that blocks on every caveat teaches senders to stop writing them.** "Never broken" still
  > rides the receipt and still departs. `web/lib/departures.ts` gains the guard in `GUARD_ORDER` and
  > `GUARD_LABEL` — verified by INSPECTION, not by running, because that worktree has no
  > `node_modules`, and it is safe because both maps are `Record<string, …>` and the one `GUARD_ORDER`
  > consumer widens to `readonly string[]`.
  > ⚠️ **One clause taken on the builder's own authority, and it is one line to reverse — §6 item 29.**
  > Three live promises carry impossible rows, not one: LuxExperience `return_to_refund/refunded`
  > 23.27% → 25.41% (**8.4% relative**), theLook `order_to_delivery/dispatched` 9.35% → 9.47% (1.2%),
  > theLook `order_to_delivery/delivered` 8.11% → 8.11% (**0.0%**). An unconditional hold stops
  > theLook's dispatch watch — the live send this module's own docstring cites as its anchor — over a
  > tenth of a point, and the delivery one over nothing at all. So the blocking prefix is used only
  > once the two readings disagree by more than the platform's OWN bar for that
  > (`IMPOSSIBLE_LAG_MATERIAL_REL` = `govern.departure.NOISE_REL` = the deep run's
  > `_METRIC_DIVERGENCE_REL`, 0.05); below it the same finding is stated in full under a DISTINCT
  > prefix that departs, never a suffix on a shared stem, because a `startswith` match against a shared
  > stem would block both and the distinction would exist only in the prose. The ontology RESTATES the
  > constant rather than importing `govern`, and a test asserts the two stay equal so the restatement
  > cannot drift. **To make it unconditional, delete the `moved >= IMPOSSIBLE_LAG_MATERIAL_REL`
  > branch.** A rate that cannot be computed at all (a promise counted per another type) blocks either
  > way: unquantified is not the same as small.
  > **Mutation-tested across both commits, each mutant killed by the test written for it, by ASSERTION
  > rather than by a crash:** drop the deadline early-return · never call the flag · wrong denominator
  > (reached instead of reached − early) · ignore the grain mismatch · the guard never holding · every
  > caveat blocking · nothing blocking · the two prefixes sharing a stem. 🔑 The existing 55 process
  > tests all passed BEFORE the new ones existed — the #530 shape again, a guard nothing exercised — so
  > the new fixture GENERATES the out-of-order rows and counts every expectation from the table rather
  > than listing it beside the assertion. One of A4's own tests was passing for the wrong reason (it
  > asserted the impossible-lag caveat DEPARTS, which production can no longer do) and was rewritten.
  > Suite 11,293 passed, 0 failed, pytest exit 0. Verified on the live declaration, read-only: the real
  > 50,048 / 11,648 / 4,199 produce exactly *"without them the rate is 25.41%, not 23.27%"*.


============================================================
- **HB-3 · promises and findings as triggers; outcomes and the manifest's first links.** `promise_breached` and
  `finding_created` beside the five triggers; a proposed ticket and a Slack thread filed on the object they are about;
  an outcome column (ticket closed, number recovered). *The first live receipt, end to end:* Olist's dispatch promise
  (`baef6c3e/ecommerce`, 9.35% late) breaks → a framed analysis names the carrier and region → the finding lands in
  the supply-chain group's channel with its receipt → a Jira ticket is proposed and approved in Slack → the ticket is
  filed on the promise → its close is recorded → the Briefing reports the breach rate before and after, with the chain.
  Four of its seven legs stand today; three are this wave. *Falsifier:* if the pushed finding is not acted on within the
  probation window by a real reader, the automation stays on probation — a push that earns no landing is not value.
  > **BUILT 2026-09-16** (same session as HB-2's slice; the LIVE drive on Olist waits for the merge — a scratch
  > server beside the live API is the one-writer trap). What stands, each piece real and tested:
  > **The two triggers** — `promise_breached` reads the STAMPED promise numbers off the cached graph (a probe never
  > builds; fires on first sight broken and on worsening past the last fired fingerprint) and `finding_created`
  > cursors the explorer's findings by `generated_at` (house rule: first observation fires; `domain`/`min_confidence`
  > narrow); both ride `probe_state`, commit on fired ticks (`commit_hub_baselines`), and PUBLISH a payload the chain
  > binds under the reserved `trigger` alias (`{"$from": "trigger.breach_rate"}`) — seeded into the chain context,
  > validated at save against each kind's closed key set (`TRIGGER_PUBLISHED`), the alias reserved.
  > **The manifest's first links** — `aughor/hub/links.py` (`data/hub_links.db`, registered same-commit): a ticket,
  > thread or webhook call FILED on the securable it is about, with the OUTCOME COLUMN (status·outcome·
  > number_recovered·closed_by) and stamped-measure snapshots at filing AND at close, so before/after is two recorded
  > facts. Doors: POST/GET `/links`, POST `/links/{id}/close`. Sends file THEMSELVES when their config says `about`
  > (slack_post→thread, notify→webhook/ticket) — §3.18's fifth law made mechanical.
  > **The ticket leg** — `require_approval` on `notify` parks the send as the same `outbound_send` inbox kind
  > (SP-7's machinery, two new three-line grant adapters keyed by trigger_id for "always allow"); the accept FIRES
  > the trigger, and the transport now KEEPS the success body — Jira's created key is parsed into
  > `ActionLog.resource_ref` (it was discarded; the ticket's key existed nowhere) and published as a bindable
  > (`notify` publishes `resource_ref`/`link_id` now).
  > **Routing in anger** — `route_about` on a notify hands the destination to the MAP: HB-1's `route()` gets its
  > first production caller; a promise's meaning chain is STRUCTURAL (`promise:<process>.<noun>` ⇒ parent
  > `process:<process>`), the owner read best-effort off the cached graph, each group destination fired through its
  > own channel trigger with the full per-destination path (approval, departure gate, filing) and no-channel
  > principals reported honestly.
  > **The falsifier, structural** — a probation push unmarked past `PROBATION_WINDOW_DAYS` (7) counts AGAINST
  > precision as `unlanded`; an automation cannot graduate by silence, and a late mark converts.
  > **The Briefing's chain leg** — `promise_chain_findings` folds a deterministic "Promises" domain beside the
  > metric moves (same provider seam): breach rate at filing vs now, the chain (`webhook … → ticket OPS-123`), the
  > recorded outcome; on frozen data it says "unchanged at 9.35%", because it is.
  > **Receipt held as a test** (`test_hb3_links_receipt.py::test_the_receipt_chain`, every store/gate/grant/route
  > real, the outbound HTTP the one stub): breach → routed landing in the supply-chain group's channel with NO
  > channel named in the chain → filed → ticket proposed/approved/fired (OPS-123) → filed on the promise → closed
  > with outcome → the Briefing block reports the chain with before==after stated honestly. **Open in the wave:**
  > the LIVE Olist drive (post-merge: declare the group+channel live, arm the chain, the 09:00Z tick); a Slack
  > THREAD filed from the accepted-proposal send path (the unattended path files; the inbox slack accept does not
  > yet); `domain`-tag routing facts at the dispatch site; UI for links/probation queues (doors serve JSON).
- **HB-4 · the provenance envelope and one ranker**, as above, with the harness arm per source kind. *Receipt:* the
  same question answered with and without conversation-derived notes on the ON-10 sets; notes stay in the prompt only
  with measured lift. *Falsifier:* R4's — a source kind that regresses is stored and shown, never injected.
  > **BUILT 2026-09-16** (same session as HB-2/HB-3). What stands: **the envelope** (`hub/provenance.py`) — source
  > kind · author · scope · observed-at with per-kind decay · verification · blast radius, with the closed authority
  > ladder (measured > approved > declared > mined > said > inferred; unknown ranks LAST, fail-closed) and the
  > roadmap's exact reader stamps (`[measured 2018-09-11, this connection]` · `[said by Ana in #ops, 3 days ago,
  > unverified]`) — generalising the substrate PX-5 already held (`DefinitionSource` + `ontology/authority.py`'s
  > verified-outranks-authority, measured before building). **The ranker** (`hub/ranker.py`) — deterministic on the
  > three axes; per-kind recency (a definition's current approved version wins regardless of age · an observation
  > decays and expires unless re-affirmed, 30 days · a measurement ranks by the data's own as-of); conflicts:
  > different tiers — the higher wins and the loser is a FLAG in the receipt; same tier — both survive and the
  > conflict is surfaced, never guessed (the ambiguity-ledger hookup rides the first real conflict); the budget fill
  > SAYS WHAT IT DROPPED. **The gate** (`hub/injection.py`) — `INJECTABLE_SOURCE_KINDS = ()`, a closed constant
  > flipped only by a change citing a dated harness receipt; while empty the block renders `""` and every prompt is
  > byte-identical (tested). Wired into BOTH prompt seams in lockstep — `grounding._BLOCKS` ("hub_notes") and
  > `_stream_chat`'s prepend — with a test that fails when either loses the block, since nothing else does.
  > **The harness arm** — `notes` in `evals/ablation_eval.py` (UNGATED by design: the arm measures what the gate
  > asks), with the inert-drop guard ("a notes arm with an empty block is the raw arm under another name" — dropped,
  > not spent on). **The receipt's honest state:** no conversation notes exist yet for the ON-10 questions, so the
  > arm inert-drops, the gate holds, and "stored and shown, never injected" IS the shipped behavior — R4's stance by
  > construction. The arm's first real measurement runs when arrivals accumulate notes; the flip, if lift measures,
  > cites its dated results file. **Open:** more adapters as kinds earn arms; the ambiguity-ledger ask-once wiring on
  > the first live same-tier conflict.
- **HB-5 · arrivals from people and systems.** A sentence in Slack becomes a note on the object with provenance (blast
  radius decides what applies and what waits); live Jira and Confluence state through Atlassian's MCP server on the
  allowlist — no connector code, the write slice's grant law already governs "open a ticket"; the email channel in both
  directions, keyed on the Google OAuth client only the user can create (24 f); one conversation record wherever it
  moves (Slack → deep analysis → Jira comment → email). *Falsifier:* an inbound channel that carries untrusted text
  reaches the agent only through customs — a red-team set of injected instructions must land as data, never as acts.
  > **FIRST SLICE BUILT 2026-09-16** (with HB-4, one branch). The Slack half: **a sentence becomes a note on the
  > object, deterministically** — HB-3's thread→object link is the router (a reply lands in a thread the platform
  > FILED on a securable, so the reply is about that securable; no model decides). The verb is explicit and
  > colon-strict: `@bot note: carrier X was on strike` files; `note that revenue dipped?` is prose and still asks —
  > which keeps the whole path inside `app_mention`, so NO new Slack scope and NO reinstall. The door
  > (`POST /arrivals/slack`) runs customs in order — cap (500), control-strip (`prompt_safety`), PII redaction
  > (`security/pii.redact_text`, the row scanner's patterns given a free-text seam) — then stages an OBJECT note
  > under `agent_notes`' blast-radius law (the new `object` target ALWAYS stages, even at high confidence: an object
  > note is read by everyone who opens the object). Provenance rides the staged recommendation verbatim; `GET
  > /arrivals/notes` is the stored-and-shown surface with the stamp on every row; the envelope adapter feeds the
  > ranker from the same store. The TS bot (`bots/slack`) gained the verb + `createArrivalPoster` (70/70 vitest).
  > **The falsifier is permanent** (`test_hb5_arrival_redteam.py`, SP-6's contract extended inbound): seven attacks —
  > instruction override, fake tool-result framing, fenced fake proposal, exfiltration nudge, 10KB bulk, SQL
  > injection, PII smuggle — each lands as a capped, redacted, PENDING note; the action inbox, the automations
  > library and the links store are unchanged by every one. **Deliberately not built:** the email channel (both
  > directions keyed on the Google OAuth client only the user can create — §6 item 24 f holds); Jira/Confluence
  > state arrives through the allowlisted MCP consumer with the write slice's grant law, no connector code, and its
  > live receipt waits on a real Atlassian server on the allowlist; a plain (non-mention) thread reply stays
  > un-listened (it would need `message.channels` + a reinstall — the mention verb covers the case without either).
  > "One conversation record wherever it moves" is the manifest ordered by time: the thread link, the ticket link
  > and the notes all hang off the one securable.
- **HB-6 · the map and the packs.** Every automation on one screen — trigger, destinations, grant, owner, last run,
  cost, probation state (Agent Ops' Map does this per agent; hub-wide does not exist); a function pack ships its group,
  its tags, its default grants and subscriptions, and its automations (24 c). *Receipt:* installing a supply-chain pack
  creates the group, tagged and subscribed, waiting for members.
  > **BUILT 2026-09-16.** **The map** is one read — `GET /hub/map` — assembling every column the sentence names
  > from stores that all existed: the trigger is the condition's own one-liner; a routed notify's destinations are
  > resolved through the ENGINE's resolver, so the map cannot drift from the send; grants are the standing rows
  > bucketed by their automation owner; **cost is an explicit floor** (the session-log fold over each chain's run
  > traces and step investigations, `unpriced_calls`/`calls_without_usage` carried — there is no per-automation
  > usage axis, and a tick job's own meter reads ~0 by construction while the inner investigation job holds the
  > spend); an unmeasured precision renders null, never 0%. The screen is Agent Ops' **Hub** layer beside the
  > per-agent Map, and it takes no connection scope — hub-wide is the definition, the door's `?conn_id` serves
  > narrow callers. **The packs half**: `function.yaml` + `POST /packs/{id}/install` — guarded
  > (`govern.guard("pack.install")`), journalled (`pack.installed`), validate-everything-then-write (a bad layer
  > refuses whole with nothing written), idempotent, and it never takes back what operators set. The shipped
  > `packs/supply-chain` IS the receipt, held by `test_hb6_packs_ship_groups.py`: installing it creates the group
  > — tagged via subscribe grants on its domains, subscribed to the order process, zero members — with its
  > dispatch watch declared `pack:supply-chain`, on probation, disarmed; and `route()` already finds the group as
  > a destination, channel-less until someone gives it one. §6 24 (c) taken with the wave.

**Sequencing rules that bind the arc.** No channel is built before an automation with real traffic needs it. The
routing half precedes enforcement. Departures are gated harder than the screen from the first one. Push only from
where the platform runs — no hosting question is reopened here. **The arc's measure is landings, not doors:** an
answer read in its channel, a proposal taken, a ticket closed and the number that recovered, a definition change
acknowledged by the people it reached. A hub with forty channels and no traffic is the kinetic plane again (§7).

**Not this:** a foreign flow engine as the schedule (§4.2, §4.3 — the automation engine has the primitives); a copy of
the data or a write-back to the warehouse; an agent that executes rather than proposes; a model that decides who
receives what or which context outranks which; a layer taxonomy of people; a ninth store for context; renamed
nomenclature for the analogy's sake; a persona named "Analyst".

---


### 3.19 · Arc IN — the install: what Hermes Agent's installer teaches (drafted 2026-09-17 at the user's direction — §6 item 25; **ALL FOUR WAVES MERGED #531**, squash `2ae9ae9d`, 2026-09-20, at the user's instruction *"we are stuck with IN arc since a long time.. just take it all in one go and finish the Arc"* — which OVERRODE the "finish Arc IP first" order recorded below, and why item 25 (a) went unstamped until 2026-09-21: the arc shipped on a direct instruction, and was stamped as shipped afterwards)

> **Origin.** The user, 2026-09-17, with a screenshot of Hermes Agent's Quick Install
> (https://github.com/nousresearch/hermes-agent): *"I like how hermes does it here… Im not suggesting to the exact same
> but lets see what we learn from it as far as installation goes.. no code change for now"*, then *"Lets add this to
> the roadmap first.. I want to finish IP arc first though.."*

**The study, read 2026-09-17** — Hermes' README, its `install.sh` and `install.ps1`, and its installation guide; read,
not run. Hermes installs with `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash` (Linux, macOS, WSL2,
Termux) or `iex (irm https://hermes-agent.nousresearch.com/install.ps1)` (native Windows): uv, Python 3.11, Node.js,
ripgrep and ffmpeg, and on Windows — because Hermes runs shell commands — a portable Git Bash under
`%LOCALAPPDATA%\hermes\git`, no admin. The code lives in `~/.hermes/hermes-agent` (`/usr/local/lib/hermes-agent` for a
root install), the data and config in `~/.hermes` (`HERMES_HOME`). Then `hermes setup` (a wizard, `--skip-setup` skips
it), `hermes model`, `hermes update`, `hermes doctor`.

**Where Aughor's install already holds its own — keep these.** The Node.js download is SHA-256-verified against
nodejs.org; Hermes' Windows installer verifies none of its downloads. One line per step, the tools' output in
`.aughor/logs/`, and a failed step shows its log's tail and the next action. A re-run skips what did not change (`npm ci`
per lockfile, `next build` per fingerprint). The installer is standard-library only, held by tests, and CI runs it on
three operating systems. It ends in the running app with the browser open, where Settings → Models is. No shell rc
file is edited: the `aughor` command sits in uv's own command folder. A download cut off halfway runs nothing, and
`install.sh` is POSIX `sh`.

**What it teaches — measured against Aughor on main `1c150b05`:**
- **Code and data apart.** Hermes keeps its checkout and its data in different places. Aughor's state is `data/`
  inside the checkout, relative to the folder the API starts in (`aughor/db/paths.py`: `AUGHOR_STATE_DIR`, else
  `Path("data")`). Deleting or re-cloning `~/aughor` deletes the connections, history and receipts with it, and a
  process started from another folder reads another `data/` — the shape behind the one-writer rule §7 records.
- **Update is a command.** `hermes update` fetches and fast-forwards, backs up a broken checkout and pins a commit
  (`--commit`, refusing a rollback without `--force-commit`); re-running the installer on an existing clone updates it.
  Aughor's `find_checkout` reuses an existing `~/aughor` as it is: a re-run re-syncs dependencies and never pulls, and
  there is no `aughor update` and no pin.
- **A doctor.** `hermes doctor` names missing dependencies, storage problems and PATH. Aughor's CLI (`seed`, `up`,
  `ask`, `ontology-docs`, `graph-export`, `packs`, `industries`, `skills`) has none; `aughor up`'s boot summary is the
  nearest thing.
- **The README says what the install does:** the platforms, what gets installed and where, "no admin", and the known
  Windows Defender false positive on `uv.exe` with the exclusion command. Aughor's Quick start is two commands and
  "Next time, run `aughor`".
- **Questions stay off the unattended path.** Hermes' Windows installer asks nothing (no `Read-Host`); its shell
  installer reads stdin, else `/dev/tty`, else takes the default, and `--non-interactive` skips every prompt. IP-2's
  industries question hung both Windows install jobs on PR #518's first CI run — a console without a window — until
  the question required a person: no `CI`, and on Windows a console with a window.
- **Hostile networks.** Hermes probes the network before the heavy steps, retries the clone and falls back to a
  blobless clone when GitHub throttles, degrades its Python dependencies in tiers (all, all minus the broken, core
  only), explains corporate-proxy certificate errors (`NODE_EXTRA_CA_CERTS`) and normalises long Windows profile paths.
  Aughor says "check your internet connection".
- **A short address.** Its own domain keeps the one-liner short and independent of the repository's layout. Aughor's
  Windows line wraps `irm | iex` in `powershell -ExecutionPolicy ByPass -c "…"` on purpose, so it runs from Command
  Prompt too (#501).

**Waves** — none built; each lands as its own measured slice:
- **IN-1 update and doctor.** `aughor update`: a clean clone fetches and fast-forwards; a dirty or diverged one is
  refused with the reason, never reset; a snapshot install re-downloads into place; `--ref` pins; the installer's
  steps re-run. Re-running `install.sh` or `install.ps1` on an existing clone does the same. `aughor doctor`: uv,
  Python and Node.js with their versions, both ports, `data/` writable, the `aughor` command on PATH, a model
  configured — answered without a model call and without a query against a warehouse.
- **IN-2 the README's install section:** the platforms (WSL2 once measured), what gets installed and where, no admin,
  the disk it takes, update, uninstall, non-interactive installs (`--industries`, `--no-start`), and troubleshooting
  (Defender on `uv.exe`, a corporate proxy).
- **IN-3 hostile networks:** a preflight before the slow steps, retries on the clone and the downloads, the
  proxy-certificate hint.
- **IN-4 a data home.** Aughor's state outside the checkout — per user (`~/.aughor`, `%LOCALAPPDATA%\aughor`), one
  env override — and a one-time move of an existing `data/`, verified before anything is removed. The largest wave: it
  touches every store path and the test isolation behind them, so it gets its own plan before it starts.

**Recommended not to copy** (the builder's view; item 25 (f) is open): a portable Git Bash — Aughor runs no shell
commands, and a Windows machine without Git already installs from a zip snapshot; Termux — a Next.js build does not
belong on a phone; a root, multi-user install; a machine-readable stage protocol (`--manifest`, `--stage`, `--json`)
until there is a desktop app to drive it; shell rc edits — uv's command folder already reaches PATH.

---

### 3.20 · Arc JD — the judgment seam: a typed question is not a paragraph (drafted 2026-09-17 at the user's direction; **RECORDED HERE 2026-09-20**, renumbered — §6 item 28; studies: `docs/TYPESAFE_JEV_STUDY_2026-09-17.md` and its +1, `docs/JEV_ALIGN_STUDY_2026-09-19.md`; **JD-2's premise MEASURED AND REFUTED 2026-09-20**, `8797dfef`; **JD-4, JD-1 and JD-3 BUILT and MERGED #535**, squash `583c8d9f`, 2026-09-21, with JD-2's three survivors, A3 and A5; JD-3 ships OFF behind `semops.banded_cascade`. **RECEIPTS, later the same day:** JD-3's taken and re-decided on total tokens after the seam slim (falsifier quiet, flag still OFF), and **JD-5's taken LIVE against the real Jev** — the operator entered the key and asked for the keep-or-throw answer; verdict KEEP, `docs/JEV_LIVE_RECEIPT_2026-09-21.md` — **and then, on the user's word ("Flip the flag on and build the Jev binding"), JD-3 GRADUATED to default-ON and JD-5's production binding was BUILT** (`aughor/judgment/jev.py`, flag `semops.jev_cheap_tier` OFF, four gates, house-tier fallback). JD-4's own corpus receipt is still blocked on faithful rows, but its shuffled-context control was exercised live that night and did its job. This header read "nothing from the JD series built" after the merge — §5's prose-rot lesson again, corrected 2026-09-21, and again the same night when "none of the three JD waves has its receipt" had itself rotted)

> ⚠️ **Read the numbering before the arc.** This text was written 2026-09-17 on
> `origin/claude/fervent-cori-w9ogfc` (`93112558`, ROADMAP.md +106) and it claimed **§3.19 and §6 item
> 25**. Arc IN was drafted the same day, landed on main first, and holds both. Arc JD is therefore
> renumbered to **§3.20 / item 28** and Arc IN is left exactly as it stands — the arc that arrives
> second renumbers. **Item 28 sits after items 26 and 27, which were both decided 2026-09-19, although
> this arc predates them by two days.** The register is ordered by the number a thing was given, not by
> the day it was drafted, and no other line in §6 would tell a reader that.

**The observation.** TypeSafe shipped a model class that gives up text generation and returns typed,
calibrated decisions — one **state**, N independent **questions**, each a Choice (one of a closed set,
with a probability per option), a Score (a position on 2–10 ordered levels, which may fall between
them) or a Noul (the probability a proposition is true). `vinnylarouge/jevlike` re-derives the *shape*
in 400 lines of MIT PyTorch: an option becomes a query, it attends over the context, one dot product
scores it, a softmax runs across the options — one forward pass instead of writing an answer word by
word. Neither is adopted here. **What is adopted is the request shape**, which we can have on our own
providers today, and which the study shows we are already approximating badly in two hot places.

**What is true today (measured first-hand 2026-09-17; anchors re-verified on this tree 2026-09-20).**
The deep path's wall-clock is ~100% phase-serial LLM calls (`AGENT_NOTES.md:215`): 373 s serial
against 304 s with `ada.parallel_phases` = **1.23×**, both arms 14 calls, and the note's own verdict is
that intake and synthesis dominate and phase-level parallelism is spent. Intake is ONE decoder call
carrying **28 fields** (`aughor/agent/prompts_investigate.py:761`, `IntakeOutput`, re-counted
2026-09-20 — the study said ~25 at `:755`) of which about ten are pure judgments over one state
(`descriptive_only`, `cross_sectional`, `metric_is_ratio`, `claim_type_suggestion`) and three are picks
from a set the schema already holds (`date_column`, `metric_table`, `dimensions`) — asked as free text,
then repaired: "collect ALL spec errors and fix them in ONE combined LLM retry (was up to 3 sequential
round-trips on the critical path of every investigation)" (`aughor/agent/investigate.py:5654`), with
the date column repaired deterministically by `_resolve_date_column` (`:1452`) because asking again is
less reliable. The semantic operators put 25 rows in one prompt (`aughor/semops/operators.py:32`,
`DEFAULT_BATCH`; cap 200 at `:31`), so a row's verdict can be moved by its neighbours, a parse failure
loses all 25 verdicts fail-open, and the champion cascade escalates **all** 200 rows on a sampled 20%
disagreement (`_CHAMPION_ESCALATE = 0.20`, `:141`) — paying the strong tier for the rows the cheap tier
already had right. And `earned_confidence` is COMPUTED, never asserted by the model
(`aughor/agent/state.py:253`) — the right instinct, and the exact seam a calibrated per-item
probability belongs in. The gates a hosted backend would have to ride already exist: `security/pii`,
`govern/outbound`, `govern/guardrails.py`, and the 428 `approval_required` graduated gate
(`aughor/govern/actions.py:166`).

**The arc in one line:** make a judgment a first-class call with a declared answer space, an isolated
per-question score, and a probability our code bands on — then measure it with a control before
believing any of it.

- **JD-1 — the seam.** `judge(state, questions) -> answers` over the EXISTING providers: one call per
  bundle, one closed schema per question (`noul` / `choice` / `score`), each question scored on its own
  against the state, answers keyed by question id and carrying a probability. Flag-gated,
  default-byte-identical, one backend at first. *Receipt:* the same bundle answered through the seam
  and through today's path agree on the golden set. *Falsifier:* if isolation changes no answer and
  saves no call, it is ceremony — drop it.
  ✅ **BUILT, MERGED #535** (`583c8d9f`, 2026-09-21). Three kinds after Jev — Noul, Choice, Score. A choice
  or a score is a sub-model with one probability field per option, so there is no field in which to name
  an option that does not exist; the answer is the highest-weighted option, read back in code. A failed
  call makes every answer unavailable with its reason, never a raise, and `agreement()` takes the receipt
  in one call, counting an unanswered question apart from a disagreement. ⚠️ Two departures from the
  draft: **no flag is registered, because the seam is wired into NO production path** — its first
  consumer is JD-3, flagged there — and **the probability is STATED by the model, not measured**: the
  provider has no logprobs seam, so it is the input JD-4's ECE exists to judge, not a calibrated number.
  ⏳ The receipt and the falsifier are both model calls — the operator's spend.
- 🛑 **JD-2 — intake's judgments leave the prose call. THE PREMISE IS REFUTED (2026-09-20); the
  closed-option-list half does not proceed.** As drafted: the ~10 judgment fields become typed
  questions, and `date_column` / `metric_table` / `dimensions` become **choices over the real schema**,
  which cannot return a column that does not exist — argued as monotonic by construction, and therefore
  provable below the ±7–10 noise floor. **The measurement, taken on this branch:**
  `evals/intake_validity_eval.py` scored 202 threads / 201 investigations (29 Jun – 19 Sep) against the
  schema block persisted WITH each run (`filtered_schema` on the spec — the list the model was actually
  handed, and the one ground truth that cannot drift). **1,833 of 1,835 picks — 99.9% — were names the
  model had been shown**: `metric_table` 201/201, `date_column` 183/185 (98.9%), `dimensions`
  1,449/1,449. 0 of 202 threads had their spec rewritten mid-run, so this is what the runs used, not a
  proposal a repair caught. **The falsifier fires:** a closed option list removes a failure that is not
  happening.
  🔴 **And the first number was mine, and it was wrong.** `5176820e` claimed ~20% of deep runs used a
  table or column that does not exist, from the same corpus; `8797dfef` retracts it. The harness had
  compared three-month-old specs against today's `data/*.duckdb`, and `workspace` — which owns 140 of
  the 202 specs — is a `local_upload` connection whose tables live as CSVs under
  `data/uploads/default/workspace/`, never opened. Re-pointing per connection swung the rate to 46%,
  equally meaningless, because `missimi` is a schema the workspace no longer has. **Both numbers
  measured warehouse drift and called it model behaviour.** Matching is by identifier TOKEN, not
  substring, because a substring test would count `order` as shown on the strength of `order_id` — an
  error in the direction that flatters the retraction; a run that persisted no schema is excluded
  rather than scored as a miss, which is precisely the mistake the retracted version made. Both rules
  are pinned by `tests/unit/test_intake_validity.py`.
  ✅ **What survives the retraction, and is worth fixing on its own merits:** `dimensions` is validated
  against the schema nowhere; the `metric_table` correction retry is accepted without re-validation
  (`aughor/agent/investigate.py:5676`); and no counter or event fires on a spec repair, so the
  spec-repair retry rate JD-2 named as its receipt **is not instrumented and never was**. Those are
  real defects. They are simply not evidenced by an invalid-name rate, because there isn't one. This
  refutation says nothing about whether the picks were the RIGHT ones — only that they were real — and
  it does not touch the other half of the Jev proposition, the calibrated probability.
  ✅ **All three survivors FIXED in #535.** `dimensions` validated by exact column name, reusing
  `_typed_columns`, failing OPEN on an expression or an unparseable schema because a false alarm buys a
  paid retry; the correction retry re-validated, and a spec still invalid after one correction is kept
  (no loop) and noted in `intake_notes`; and spec repair counted —
  `deep_analysis.spec_repair.{attempted,repaired,still_invalid}` and `.error.{metric_table,dimensions,windows}`.
  ⚠️ No harness drives the intake node, so the re-validation branch is exercised only through the shared
  validator.
- **JD-3 — bands, not batches, in the semops cascade.** `semantic_filter` / `semantic_top_k` ask one
  question per row through JD-1's seam; the champion tier is spent ONLY on the rows inside the
  uncertainty band, and the band's floor routes to a person rather than to a guess. Thresholds live in
  our code, never in the model. *Receipt:* strong-tier calls spent per 200-row filter, at equal
  agreement with today's escalation. *Falsifier:* banding costs more strong-tier calls than the sampled
  cascade → keep the sampled one.
  ✅ **BUILT, MERGED #535 — behind `semops.banded_cascade`, default OFF** (registered in EXPERIMENT with
  the question that settles it). `semantic_filter` only — `semantic_top_k` has no cascade, so there is
  nothing there to band — and only where the sampled cascade would have run (flag on AND
  `validate_sample > 0`); everywhere else the code that ran before runs unchanged. The band is 0.30 / 0.70,
  in code. A row the cheap call could not answer goes to the champion; a row still uncertain after the
  champion is KEPT, never silently dropped, and named in the notes. ⚠️ "Left for a person" is a note on
  the result today, **not a review queue**.
  ✅ **RECEIPT TAKEN 2026-09-21 — the falsifier did not fire** (`evals/semops_band_eval.py`; results, gold labels and
  rows committed beside it). 200 of theLook's product names, 3 predicates, the deployment's own models — ~75 calls on
  `gemini-3.1-flash-lite`. Scored against a gold set (3 labelings by a stronger model, majority vote; NOT human labels —
  and the three agreed on every row, which shows consistency, not independence), over the rows every arm judged:
  outerwear — banded 0 champion calls vs sampled 1, accuracy 97.1% vs 95.4% (175 rows): **holds**; aimed at women —
  banded 3 vs 1, accuracy 94.7% vs 92.0% (150 rows): **inconclusive by the rule**, banding MORE accurate by more than the
  2-point tolerance; accessory — banded 1 vs sampled 9, 98.7% vs 100% (75 rows): **holds**. Today's batch prompt errs
  only by keeping (8 and 12 wrong keeps, never a wrong drop); the seam's per-row question makes fewer (5 and 8). Every
  difference is 1–4 rows: a direction, not a proof.
  ✅ **DECIDED BY MEASUREMENT 2026-09-21 — YES on quality, with a token cost.** Re-run at scale with the yes/no rule fixed
  BEFORE the runs (`--decide`, `DECISION_MARGIN`): 800 product names × 6 predicates, gold labels on all 4,800, two setups —
  A as deployed (both tiers `gemini-3.1-flash-lite`) and B with `deepseek/deepseek-v4.1-flash` as the champion. **A: banded
  95.1% vs sampled 92.7%, +2.4 points (95% CI +1.1 to +3.8) over 2,350 rows, 4 champion calls vs 12. B: 96.4% vs 92.9%,
  +3.6 (CI +1.9 to +5.4) over 1,375 rows, 2 vs 7. YES on both by the rule.** ⚠️ The cost the rule did not weigh: banding's
  per-row question sends ~65% MORE cheap-tier tokens, and the sampled cascade seldom escalates, so in TOTAL banding costs
  ~60% more tokens — for fewer silently wrong rows. ⚠️ Disclosed: A read INCONCLUSIVE until a bug in the pooling was fixed
  after the runs — filters that lost every row (Gemini's quota ran out at ~20:50 mid-batch) still counted their champion
  calls, which the quota failures had inflated. B has only 7 usable filters; the gold is model labels.
  🔴 **NOT switched on — the arc's goal is FEWER tokens, and this spends more** (the user, 2026-09-21: *"The whole point
  of adding the Jd arc was to reduce the tokens"*). Measured offline on one 25-row call, prompt AND schema: today 2,306
  chars, banded 8,987 (~3.9×) — the harness had counted the prompt only. Cause: `_banded_verdicts` puts each row's text in
  its Noul proposition, and `seam._field_for` copies the proposition into every schema field's `description`, so every
  row travels twice. ⏳ NEXT: slim the seam (condition once, row once, bare schema fields — est. ≈ today's size), count
  schema tokens in the harness, and re-decide on TOTAL tokens (as accurate AND no more tokens) — the accuracy gain must be
  re-measured, since part of it may come from the verbose prompt.
  ✅ **SLIMMED AND RE-DECIDED 2026-09-21** (`docs/JEV_LIVE_RECEIPT_2026-09-21.md` §2). Rows now ride in the STATE once, in
  the same `[index] text` listing the sampled path sends; each question is a short reference to its row; a noul's schema
  field is its id and its [0,1] bound, nothing else — the schema constrains, the prompt carries. Same builders, same 25
  rows: **9,021 → 5,228 chars (0.58×)**, against today's 2,340; the remaining 2.23× per-call floor IS the per-row-field
  isolation. Recorded totals re-cost at the measured ratio: **banded ≈ 0.92× sampled on BOTH setups** (A ≈ 44.5k vs 48.3k;
  B ≈ 25.5k vs 27.8k) at unchanged accuracy (+2.4 / +3.6 points) and unchanged champion counts (4 vs 12; 2 vs 7) — **the
  token falsifier no longer fires**. ⚠️ A deterministic re-cost of the recorded runs, not a live re-run (no funded LLM
  backend on this machine that night: Gemini quota shared and spent, Groq 401, Together 402); the harness now records
  per-arm wall-clock and per-row probabilities, so the confirming live run also buys the LLM-side ECE that is still
  unmeasured. Flag still OFF — the flip is the operator's, now with the numbers on the table.
  ✅ **FLIPPED 2026-09-21, the user, on the receipts: "Flip the flag on."** `semops.banded_cascade`
  GRADUATED to FLAG_DEFAULT (default-ON, the `ask.converse` shape): the sampled cascade stays alive as
  the off-arm, `AUGHOR_SEMOPS_BANDED_CASCADE=0` is the kill switch, and the graduation guard in
  `test_feature_flags.py` was widened deliberately with the receipt. The two sampled-cascade tests now
  opt into the kill-switch arm explicitly — the off-path keeps its own tests, as a live off-path must.
  🔴 **Two findings about this deployment, bigger than the receipt:** (1) the cheap and champion tiers are the SAME model
  (`fast` = `coder` = `gemini-3.1-flash-lite`), so today's cascade spends its "strong" calls re-asking the model it is
  checking — the first run escalated all 200 rows on one predicate to do exactly that; a real champion is the user's
  model choice and would make this receipt mean what it says. (2) that model returned EMPTY structured output on 4 and
  then 8 of ~75 calls (5–10%), not content-driven — the batch with the most explicit names never failed — and
  `semantic_filter` keeps a failed batch whole (fail-open), so in production 25 rows no model judged are kept with only
  a note. The harness excludes such rows from every arm; production does not.
- **JD-4 — the instrument, and it comes first.** `jevlike/eval.py`'s battery adopted as a standing
  guard on every judgment seam: top-1, expected calibration error over ten bins, and the
  **shuffled-context control** — every question paired with the WRONG state, on the rule that a
  judgment must beat that control to count. *Receipt:* the control run on our own logged judgments.
  *Falsifier:* if real and shuffled score within noise, our judgments are not reading the state and the
  rest of this arc is pointless. 🔑 JD-2's retraction is the argument for building this first: the arc's
  one measured claim was wrong for three days because its ground truth drifted, and the harness that
  caught it costs no model call.
  ✅ **BUILT, MERGED #535** — a free harness in `evals/` plus a hermetic companion in `tests/unit/`, the
  shape its two siblings use. **Its first run on the live corpus (58 rows, all `converse.tool`, 18–20 Sep)
  took no reading on three of its five measures, each with its reason, and that is the finding:** top-1
  has no reference (`outcome` is `ok` on all 58 — A1's constant, because no decision had been recorded
  since A1's code reached that machine); ECE has no probability (`confidence` 0.0 on all 58 —
  `converse.tool` NEVER produces one, `ask.route` records one and has no traffic, `framing.definition`
  has one behind a flag whose ON arm has never run); and the shuffled control was blocked on FIDELITY,
  not cost — no row's prompt was recoverable. Measured free: **`choice_prior` = 44.8%** (always
  `run_sql`) against a 2.6% uniform baseline — the floor a control must beat, published before any
  control runs so an arm at ~45% cannot later read as a pass.
  The control was then made takeable, in the same PR: every decision row carries a sha256 of its
  assembled prompt, and the first decision of a turn records the prompt BUILDER'S ARGUMENTS — gated by
  the operator's capture window, closed by default — so a replay swaps ONE argument and rebuilds, and
  refuses a drifted rebuild before spending a token. (Recording the assembled prompt was the obvious
  fix and was wrong: the state lives inside that string, and swapping whole prompts moves five things
  and attributes them to one.) On the live corpus that is **0 faithful rows**: 44 mid-loop, never
  replayable; 14 recorded before the fingerprint existed. And **46 of the 58 rows (79%) had been filed
  under `converse.tool` when the analyst made them**, because the site was a literal in the loop;
  `analyst.tool` is its own site now.
  ⏳ The control run itself: rows recorded under an open capture window, then model calls.
- **JD-5 — the hosted binding, optional and last.** Jev behind JD-1's seam as one backend among ours,
  OFF by default, riding `govern/outbound` and the PII gate because the state is customer row text
  leaving the box, surfaced in the Trust Receipt, and never on the verdict path: on TypeSafe's own
  four-workflow benchmark Jev scores 67.8% against Opus 5's 73.1% — it is a speed and cost result, not
  an accuracy one. *Receipt:* the same JD-4 battery, both backends, same bundles. *Falsifier:* no
  wall-clock or cost win at equal calibrated accuracy → refuse and record it in §4.
  ✅ **RECEIPT TAKEN LIVE 2026-09-21 — the falsifier did not fire, and neither did JD-4's control**
  (the operator entered `TYPESAFE_API_KEY` and said *"prove me the value … if yes, we keep it; if not,
  we throw it out"*; `docs/JEV_LIVE_RECEIPT_2026-09-21.md`, numbers in `evals/jd5_jev_receipt.json`).
  `jev-1.13.0` live against the recorded arms, paired on the same frozen rows and gold, 5,400
  row-judgments for ≈ $0.011: **jev-solo 95.3% vs production's sampled 92.7% (+2.6, CI +1.1 to +4.2,
  12 filters / 2,350 rows)**, parity with the full banded LLM cascade (+0.2, CI −1.3 to +1.9) at
  **zero** champion calls; the composed jev+champion cascade matches or beats sampled with 1 champion
  call against up to 9. **JD-4's shuffled-context control, exercised live on the eval corpus:** real
  0.975/0.990/0.945 → deranged-state 0.755/0.470/0.750, BELOW the majority-class floor on all three —
  the probabilities read the state. **Calibration, the honest part:** ECE 0.058 over 5,400 — the tails
  are excellent and the middle is not (stated 0.45–0.65 → true 19–30%), i.e. the miscalibration lives
  exactly INSIDE the 0.30–0.70 band the cascade escalates; "calibrated" is not global, the band edges
  are where trust ends, and the design survives its own audit. **$0.00196 per 1k rows** (2.6× under
  flash-lite's sampled arm at $0.25/M; Jev $0.042/M input corroborated by pg-jev's independent
  ≈$0.0405/M), 0.68 s median per 25-row bundle sequential, repeatability |Δp| ≤ 0.009 (5 flips/600).
  Fuzzy predicates are the named limit (sport: 0.86–0.90, ~4× the band occupancy) — the champion stays.
  **VERDICT: works — KEEP.** The production binding stays unbuilt and the flag stays OFF: a hosted
  dependency in the serving path, behind the outbound grant and the PII gate, is the operator's flip,
  now with numbers. `pg-jev` (same model behind a Postgres-superuser-only surface, managed hosts
  excluded by its own README) examined and NOT adopted — semops already sit at the seam and speak every
  warehouse; its batch-degradation measurement (≤20 rows 100%, 40 → 92–98%, 80 → 77–94%) pins our
  batch at 25 and is the second first-hand-adjacent source for the price.
  ✅ **BUILT the same night — the user, on the receipt: "Flip the flag on and build the Jev binding."**
  `aughor/judgment/jev.py` behind flag `semops.jev_cheap_tier` (EXPERIMENT, default OFF), the cheap
  tier of the banded cascade only, never the champion, never the verdict path. Four gates, each
  failing toward the house: the flag; loud configuration (`TYPESAFE_API_KEY` AND `AUGHOR_JEV_MODEL` —
  no model id ships in the product, so the operator names even "jev-latest"); a PII scan that
  withholds a bundle WHOLE on any redactable cell (a withheld bundle's rows come back unanswered,
  which the band already routes to the in-house champion — conservative over clever, because a
  governance gate that parses its own prompt has a parsing bug waiting inside it); and
  `govern.outbound.external_call("typesafe","systemone")` — cap before send, span, EXTERNAL_CALL
  event, so every call is countable. The seam itself now DISPATCHES to any judge-shaped backend after
  its own misuse checks, which is what "one backend among ours" means in code. `FallbackJudge` is the
  outage guarantee: a bundle Jev cannot answer (withheld, blocked, down, unconfigured) is re-judged by
  the house cheap tier through the same seam — an outage degrades to yesterday's cascade and NEVER
  floods the champion (pinned by test: Jev dead → house tier 1 call, champion 0). The third party is
  NAMED in the cascade's notes where the Trust Receipt reads them. 11 hermetic tests
  (`tests/unit/test_jev_binding.py`); smoke-tested LIVE through `semantic_filter` end-to-end the same
  night (5 rows: peacoat+puffer kept, cap/belt/socks dropped, 0 champion calls, note names the judge).
  The deployment's `.env` carries the key, the model and the flag; they take effect when this branch
  merges and the API restarts. Open question on the flag's EXPERIMENT entry: does the live deployment
  hold the receipt's numbers at its measured ~7% band occupancy, or does the fallback rate say the
  house tier is doing the work anyway?
- **JD-6 — the local scorer, if JD-4 earns it.** A `jevlike`-shaped one-pass head trained on our own
  logged `{state, options, chosen}` rows, weights outside the repo and installer per §3.9's adapter
  law, used as a pre-filter and ranker (cut 200 candidate columns to 12 before a real model reads them)
  and never as a decider — its own authors measure 26–29% where controls score 8% and call the option
  head a capacity bottleneck. *Falsifier:* cannot beat a shuffled control by more than the noise floor
  → stop, and say so.

#### The alignment movement (the +1 study, 2026-09-19 — `docs/JEV_ALIGN_STUDY_2026-09-19.md`)

`sutro-sh/jev-align` at `49753df` (MIT, ~4,000 lines, read in full, **not executed** — no API key, and
a run spends a reflection model's tokens) answers the question after the JD series: where the text of a
judgment comes from, and how it gets better. Its findings are lettered **A1–A6** because when the study
was written §3.19 was contested between this arc and Arc IN; that is now settled at §3.20, and the
letters are kept so the study and the roadmap still read as one thing.

- ✅ **A1 — an outcome that can come out negative. BUILT 2026-09-19/20** (`e68beffa`, `2174fc48`,
  `79d01b44`). Measured on the live store first: **40 rows, every one `conn_id` empty, every one
  `confidence` 0.0, and `outcome` `'ok'` on 40 of 40** — because the only writer of that column was
  `tool_loop`'s inline "the tool did not raise" (`aughor/agent/tool_loop.py:235`; the study cites `:226`,
  pre-A1). A label that never takes its other value is a constant, and `exporters.list_for_export` would
  have shipped 40 positive examples. Now: `record_decision` carries `conn_id`/`trace_id`/`inv_id`,
  `mark_outcomes_for_run` closes a run's decisions from `record_verdict` on reject/correct — the first
  caller `mark_outcome` has ever had — and `accept` is deliberately NOT propagated, because a right
  finding does not establish that any individual pick was right. Measured by
  `evals/decision_yield_eval.py`, the first eval here that scores the RECORD rather than an answer, and
  it makes no model call: arm B on `ask.route`, 8 rows, attributable **0 → 8**; on `converse.tool`,
  5 rows, attributable **0 → 5**. ⚠️ Two caveats worth more than the pass: the model returned confidence
  **1.00 on all 8**, including the question both models got wrong in ON-10's receipts, so the
  probability column is populated but flat and **A2 has an input that cannot yet rank anything**; and
  because only failures produce a negative, the corpus is heavily imbalanced by construction.
- ⏳ **A2 — uncertainty schedules the human, not policy.** Blocked on JD-1's probability, and on A1's
  flat-confidence finding above. Today the only things that route work to a person are policy gates —
  the 428 approval, the departure hold — and neither knows which decisions were close. *Falsifier:* if
  audit-slot disagreement is indistinguishable from ambiguous-slot disagreement, the ranking reads
  nothing and the queue may as well be random. ⏳ **Still blocked after #535, on a different thing:**
  JD-1's seam exists, but its probability is stated rather than measured, and JD-4 found that
  `converse.tool` — the site carrying the traffic — NEVER produces one. A2 now waits on a site that
  yields a probability at all.
- ✅ **A3 — a definition change is a diff, a score, and a named population. BUILT, MERGED #535.** The
  screen beside `POST /metrics/{name}/transition`: what the definition changes from, whether it runs and
  what it reads, what it leaves undeclared, and how reproducible that read is. **ADVISORY** — it never
  holds an approval, and `definition_report.py` cannot import the module that holds a send (an
  AST-parsed import guard). ⚠️ **"A named population" did not survive measurement:** on the receipt
  target's BigQuery warehouse there is no as-of read in this tree (`snapshot.execute_as_of` is
  DuckLake-only), `return_rate`'s numerator accrues in place, and `data_version` returns None silently —
  so `Population` is a typed verdict, **pinned / fingerprinted / unpinnable**, and an unpinnable with no
  reason is a construction error, never a silent null. 🔴 Found on the way and fixed: **the approve
  button 404'd for every connection-scoped metric** — `transitionMetric` sent no connection, so the
  server looked for a global metric of that name. ⏳ Not yet driven live: the running API predated the
  route.
- ✅ **A4 — the frozen-population rule as a standing guard. BUILT 2026-09-20** (`407f0a4c`).
  LuxExperience declares a refund promise and the platform measured it: 11,648 of 50,048 Returns
  breached, **23.27%** — while the stage one level up already counted `out_of_order: 4,199`, Returns
  refunded BEFORE they were received. A negative lag can never exceed the window, so all 4,199 were
  counted as KEPT. Without them the rate is **25.41%**, the failure understated by 2.14 points in the
  business's favour, on a number that leaves the platform. Nothing was hidden; it was computed one level
  away from the reader, which is the same thing. `Measurement` now carries `caveats`, filled from the
  promise's flags on both the ontology and hub-stamp paths, and `receipt_line` states them BEFORE the
  guard list — a caveat after a row of green ticks reads as a footnote to reassurance. Guard
  mutation-tested four ways, each killed by assertion rather than a crash. Whether such a caveat should
  HOLD a send was left to the user, and answered the same day: **§6 item 29**.
- ✅ **A5 — capture as a budget, not just a tolerated write. BUILT, MERGED #535.** `record_decision`
  was observation-never-control and never raised, but had no bound: one field capped
  (`_MAX_CONTEXT = 2000`), nothing capping the store's growth or counting what was lost. Now, in the
  shape of `session_events_prune`: `AUGHOR_DECISIONS_MAX_ROWS` (default 200,000) and
  `AUGHOR_DECISIONS_KEEP_DAYS` (default **OFF** — this corpus is what A6 waits to accumulate); a row a
  person's verdict labelled is never pruned and never counts toward the cap; losses counted as
  `learning.decision_record.pruned` / `.truncated`. At 58 live rows the counter is the part that earns
  its place, as the study predicted.
  🔴 **Found beside it and fixed in the same PR: `GET /learning/decisions` served every row's `context` —
  users' questions, verbatim — to an UNAUTHENTICATED caller** (HTTP 200, no auth header, 58 rows). Rows
  are now served metadata-only, with `payload_withheld` saying why. ⚠️ Still open: the column itself is
  stored verbatim, with no retention beyond the row cap.
- 🛑 **A6 — an optimizer over definitions. HOLD, with the number.** GEPA over a definition optimizes
  against human labels; we have five verdicts, none carrying `sql_source`, unchanged in sixteen days. An
  optimizer on that corpus is an optimizer on noise. Revisit at ~150 labeled decisions with outcomes at
  a single site — the order of magnitude MI-4's gates already use. *Falsifier for the hold:* a site
  reaches that volume and a human-labeled holdout shows a proposed definition beating the incumbent
  outside the noise floor.
- 🛑 **Refused from jev-align:** the label picker that pre-selects the model's own answer — automation
  bias at exactly the screen where the human is supposed to decide.

**Not this:** a judgment model anywhere a person acts on the number it produced; a model replacing a
deterministic resolver that already works; a hosted dependency on by default, or one that sees row text
without an outbound grant; weights in the repo or installer; a second confidence vocabulary beside
`earned_confidence`; and no figure from a vendor page this session could not open treated as measured —
`docs.typesafe.ai` and `typesafe.ai` were blocked by egress, and the study says which numbers are
second-hand.

### 3.21 · Arc CB — the company brain: what people SAY, checked against what the data SHOWS (drafted 2026-09-22 at the user's *"Once done, lets consider & plan for Codos roadmap items"* — §6 item 30, four answers; **REORDERED 2026-09-22 at the user's *"reorder it that way.. and lets build the foundation first.."*: the two waves that record what cannot be backfilled come first, then owners, then the rest; CB-1 STARTED the same day**; source: the **Codos idea set**, `IDEAS.md` 15–22, whose 36 cited starting points were re-verified on `1a8a3a88` the same day)

**Thesis.** Codos builds a "company brain" from what employees write and say; Aughor's context graph is the same
machinery over what the warehouse measures, and admits no model-inferred source. Aughor's company brain is therefore
**said versus measured**: a claim a person makes comes in at the hub's `said` tier, the platform checks it against the
data, agreement raises it to `measured`, disagreement becomes a question to its owner, and what cannot be checked stays
visibly unknown. Everything else in the set is what that needs — owners a question can reach, a date on every fact, a
place to put the action — plus two finishes of machinery that already exists and shows nothing.

**Laws (standing, restated):** people edit the organisation's ontology and the platform never does (§6 item 20) · the
hub owns meaning, not data (§3.18 law 1) — no crawling of Slack history or email bodies, judged not worth copying · a
person is never linked by matching a display name (`identity/resolver.py`) · no model-inferred source enters the graph
(`context_graph.py:40`) · a question is asked once and the answer remembered (`departure.answer_owner_question`).

**Waves — in the user's order (2026-09-22, revised the same day): the foundations first — a date on every fact and the baseline at acceptance record what a running organisation cannot backfill, so they must exist BEFORE real traffic; owners next, because every later wave ends in a question to someone; then the finishes; the thesis last.** The earlier reading — "nobody has opened the Briefing, nobody has accepted a recommendation" — measured a one-person dev instance, not the design; the user's ruling is that the arc is judged by what it does for an organisation with real traffic, and by that bar it is the layer the platform lacks: who owns a number, what leadership is trying to do, what people claimed, what was decided, and whether it worked — with the one property Codos cannot have, that a claim is checked against the data.
- ✅ **CB-1 · A date on every fact, and what it replaced** (idea 16) — **BUILT 2026-09-22** (`claude/arc-cb-foundation`).
  The graph's `Provenance` carries the hub envelope's names — `observed_at`, `valid_until`, `author` — plus `observed_basis`,
  which says whether the date is the SOURCE's own stamp (a finding's `generated_at`, the ontology build that profiled a
  table) or the build's, stated because the source carries none. An old finding re-projected today keeps its own date; an
  edge is as old as the fact that asserts it. `carry_history` (pure; the store calls it before every write) brings each
  node's `first_seen`, `last_changed` and `history` across a rebuild: a changed fact keeps its old reading as a
  `FactRevision` whose `reason` is *changed* when the observation moved and *corrected* when the same observation now
  reads differently (Codos's two events, made deterministic; a build-stamped fact can only ever read *changed*); what IS
  the fact per kind is `FACT_FIELDS` (a table's columns, a metric's formula, a finding's text and SQL — never an insight
  list or a staleness mark, which would write history on every rebuild). A node a rebuild no longer emits is `retired`
  with its last state (cap 200, newest kept) and takes its history back when it returns. Consolidation keeps a superseded
  finding's text, not only its id. Receipts: `tests/unit/test_context_graph_dated_facts.py` (16) + the parity test
  updated (the projector is still one shape; the store carries the history). ⏳ Owed: the dates and history on a
  screen — they land with the map below.
- **CB-2 · Decide when to ask whether a recommendation worked, when it is accepted** (idea 22). Accepting records
  the metric, its value now and a review date; on that date the platform measures again and asks **the metric's
  owner** (the user's call, 2026-09-22 — not the accepting person, who is asked only while the owner is unresolved);
  the answer lands in `playbook.outcomes` where it already updates success rates. Depends on CB-3. This closes the
  open call *"when is a person asked whether a recommendation WORKED?"*.
- **CB-3 · Owners the platform can reach** (idea 18). An owner string on a metric, a process or a rule is linked
  to a principal ONCE, by a person, in the UI; the glossary gets an owner field; `owner_principal` resolves the link;
  an unresolved owner is shown as unresolved wherever a question would have gone. Never by name matching.
- **CB-4 · Remember a rejected duplicate** (idea 19). `GET /ontology/duplicate-entities` recomputes the same
  pairs on every read; a "no, these are different" is recorded with its reason and the pair is not offered again —
  the pattern the explorer's withdrawn proposals (`explorer._withdrawn`) and dismissed recommendations already use.
  Receipt: reject a pair, read again, it is gone; the reason is on the record.
- **CB-5 · Show how much of the business the platform can see** (idea 15). `declarations.Coverage` (imported only
  by its test) reaches a screen: the share of tables mapped to business objects, exclusions out of the denominator,
  banded; beside it *the one missing definition holding the most back*, counted from departure holds per unapproved
  metric ("approve `revenue` and 3 sends unblock" — the theLook case of 2026-09-18). Deterministic, no model.
- **CB-6 · What the company is trying to do this quarter** (idea 21). A short list of priorities, written by
  people in **organisation settings** (the user's call — already people-written, already winning over inference),
  each naming a metric and a target; `triage.impact_score` counts a finding that bears on one, and the Briefing says so.
- **CB-7 · One action beside each Briefing item** (idea 20). The single best action under each item, chosen by the
  retriever's learned success rate, sent through the SAME gated path the Recommendation Inbox uses
  (`routers/actions.py` execute door, departure gate untouched). The action goes where the reader already is.
- **CB-8 · Said versus measured** (idea 17). First source: **filed Slack thread replies** (the user's call) — they
  already arrive as staged notes (`routers/arrivals.py`) and become context pieces (`hub/adapters.py`). A reply that
  states a number is checked with `verify.verify_numeric_claims` against the warehouse; agreement → `measured`,
  disagreement → a question to the owner (CB-3), uncheckable → `unknown`, shown. A CHECKED note is the first kind let
  through `hub/injection.INJECTABLE_SOURCE_KINDS` (empty today, by design). Uploaded documents (idea 7) come after.

**The map — what Aughor offers in place of Codos's "Deploy the company brain" diagram (the user, 2026-09-22: *"lets keep this
diagram in mind and build one that aughor would offer.. a real, provable one"*).** Theirs: sources → raw data → four
observers (people, product, operations, market) → a merge-judge (dedup, resolve, write plan) → three vaults (company:
stable facts · engagement: operational record · working memory: synthesis and priorities). Ours has the same four layers
and one rule: **every box is a store that exists, with a door and a live count, and every arrow is a measurement** — so
the map is a screen, never a picture. **Sources:** the warehouse connections, dbt and the glossary, the metrics catalog,
the industry packages, what people declared (the organisation ontology), filed Slack threads and uploaded documents.
**Observers:** the profiler, the explorer, the join guard, the investigation engine, the departure gate, the prose mapper.
**The judge** (theirs merges; ours measures): the authority ladder `measured > approved > declared > said > inferred`,
`verify_numeric_claims`, finding consolidation (dedup, supersede, contested), ambiguity resolution, gate 4. **Vaults:**
*company* = the context graph — dated (CB-1), with what it replaced — plus the measured ontology and the approved metrics;
*engagement* = investigations, decisions, accepted recommendations with their baselines and outcomes (CB-2), the audit;
*working memory* = the quarter's priorities (CB-6), the north-star metrics, the business profile. Each wave lands its
count on the map: facts dated · claims checked · owners reachable · outcomes measured · sends held for a missing
definition. **Built as the arc's own surface once CB-1..CB-3 give it numbers to show; until then it is this paragraph.**

**What each wave must show before the next starts:** a live receipt on theLook or LuxExperience, a mutation test on
every new guard, and the §3 line updated the same day (a prose claim in §3 rots silently — §7).

**Refused with the set:** crawling Slack history or email bodies · entering the EnterpriseRAG-Bench race (their graph
adds ~4.5 points over plain agentic file search, by their own numbers).


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

### 4.6 · An ontology export to Microsoft Fabric IQ — REFUSED (2026-09-21)

The Fabric IQ study (§3.15, amended 2026-09-11) found that Fabric's ontology item wants exactly what Aughor
measures — object types with a verified key and a display property, properties bound to their source columns,
relationships with a cardinality, ids stable across exports — and asked in §6 item 16 whether to build an
export door. The recommendation was to defer until a customer on Fabric asked. **The user refused it outright
when asked, 2026-09-21.** The case against it on record is §0's: the measured ontology feeding this platform's
own agents is the moat, and an export hands it to another vendor's. An RDF/OWL export is the same question and
the same answer. Re-propose only with new facts: a customer on Fabric asking, and Fabric's published
item-definition format verified against Microsoft's documentation (the playground's `fabric.ts` is a community
implementation, not a contract).

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
        **§3.7's four phases are COMPLETE**; its SECOND MOVEMENT — the authored step — was drafted
        2026-09-19 and is listed under ARC DS II below)
        VA-10 multi-user + admin  (hardening pass over everything above) — ✅ UNBLOCKED
                                   2026-09-02: §6.4 decided (visible metadata, gated payloads,
                                   break-glass audited and visible to the user). §3.5 carries it.

ARC MI  ✅ ADOPTED 2026-09-03 (§6.7 both clauses YES · §6.8 YES) — first target NL2SQL,
        training rented, not owned
        MI-0 annex ✅ DECIDED (§6.7b); remaining code: the langfuse.trace.input gate
        MI-1 grade what already runs · MI-2 verdict pins evidence — substrate-sized,
             may ride alongside any band above
        MI-2b ✅ BUILT 2026-09-20, MERGED #532 (`d91fb9be`) — the journal
             had no sweep at all: 430,768 events over 95 days, 76.8% of them unreachable by
             aughor_ops's 100k snapshot; scoped retention (named chatter only, 2-day window +
             50k cap, bounded at 20k/sweep, driven by emit) · Migration 12's trace and
             retention indexes · the store facade's silent fallback made loud · the outbound
             delivery log moved to the Ledger, where it showed 336 rows, 336 failed
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
        SECOND MOVEMENT ✅ ADOPTED 2026-09-15 (§6 item 22 (a)) — authoring by sentence: the user's own
             ⌘K turn measured six breaks between a draft and an agent that runs
        SP-7 ✅ MERGED #506, widened in #511 — honest
             drafts: a real schema or none · a channel or sender the
             request did not name stays open, and Accept refuses until it is filled · the first
             run stated · drafted declared writes wait for a person · the guide's labels pinned
        SP-8 agent + its schedule, one proposal · SP-9 the approval card ✅ MERGED #508 → SP-10 show
             the work (22 b) ✅ MERGED #509 · SP-11 revise in place · SP-12 edit, monitor, brief ·
             SP-13 your timezone · SP-14 on by default (first slice; 22 d) · SP-M measure authoring
             ✅ ALL MERGED #510. The movement is closed; §3.11 carries each wave's receipts and
             leftovers. (This band read "session branch, unmerged" for five PRs after the merges —
             corrected 2026-09-21.)
ARC HB  ✅ ADOPTED 2026-09-16 (§3.18; §6 item 24 (a)(b)(d) stamped on the user's "go"; HB-1 first
        slice started the same day) — the hub: people still come to the platform, and it also
        receives data and exports intelligence. Measured 2026-09-15: no email either way, neither a
        promise nor a finding is a trigger, nothing links a thread or a ticket to an object, no
        groups, one privilege in the grant store, the reader is the company everywhere, a metric's
        quality tests never reach the Briefing. Waves: HB-0 measure ✅ → HB-1 groups and grants, the
        routing half (persona + function groups, Subscribe/Own, owner as a principal, `domain`
        grant-bearing) → HB-2 the departure gate + probation → HB-3 promises and findings as
        triggers + outcomes, first receipt on Olist's dispatch promise → HB-4 the provenance envelope
        + one ranker (a harness arm per source kind) → HB-5 arrivals (Slack sentences → notes ·
        Jira/Confluence through MCP · email, keyed on the user) → HB-6 the map, packs ship groups.
        The measure is landings, not doors. ✅ HB-1…HB-6 first slices merged (#513 · #515 · #516);
        HB-2 REMAINDER built 2026-09-17 — every outbound transport gated (AST-held), laws 1·2·4·5·6·7
        and the receipt on the message, the departures screen
        · ✅ AMENDED 2026-09-20 (§6 item 29, `7cd717e0`): the departure gate gains a `caveat` guard
        beside `trust` — a measurement that refutes its own number is HELD, above a 5% relative bar
        (`IMPOSSIBLE_LAG_MATERIAL_REL`); below it the finding departs in full under a distinct prefix.
ARC IP  ✅ ADOPTED 2026-09-14 (§3.17; §6 item 21) — industry packages, chosen at install and read
        for the connection's own industry. IP-0 ✅ MERGED #503 (`aebe5feb`): playbook reads
        scoped by industry (21 of 96 cross-industry plays → 0), the 486 dropped causes seeded,
        whole-word industry matching, definitional answers read plays, "proven" only with an
        outcome. IP-1 ✅ MERGED #518 (`1c150b05`): the KB in eleven packages behind one resolver,
        moved unchanged (measured); data-quality plays as the Verifier's rule-outs on deep reports;
        existing playbooks topped up with the 486 checks, a deleted one never resurrected.
        IP-2 ✅ MERGED #518: the installer asks once which industries (through the
        terminal, before anything slow; --industries / AUGHOR_INDUSTRIES answer ahead); one file
        narrows every industry read; Settings → Organization and `aughor industries` change it.
        IP-3 ✅ MERGED #519 (`21a4484f`): the anatomy and gate 3 (static, CI) · gate 4 measures a
        package on a named public dataset with no model · airline the reference — 3 sourced
        metrics, 8 bound plays, 14 goldens; all 14 of BTS's published January 2019 figures
        reproduced on its 638,649-flight file; 6 claims measured-true, 2 expected.
        IP-4 ✅ MERGED #520 (`7e13f64e`) 2026-09-17: gate 6 enforced — the agents read only active packages ·
        banking & lending drafted through gates 1–4 on the FDIC's per-institution data, 51 of 51
        published figures reproduced, no model. 🔴 banking ships `status: draft`, so gate 6 keeps it
        INERT until a person activates it — the next act on this wave is a REVIEW, not a build.
        Next, after that review: payments & fintech (it reuses banking's parties, accounts and
        transactions), then insurance. ✅ "The runtime reads a package's anatomy" is ANSWERED by
        #534 (`06d9d296`, 2026-09-21): measured first, the agent runtime consumed none of it; now
        an active package's plays reach the playbook store and its typed metric recipes reach the
        prompt, `resolve_recipes` and `metric_vocabulary` — gate 6 held by construction, so draft
        banking still contributes nothing. A package's questions are not covered (§3.17).
        The user, 2026-09-17: finish Arc IP before Arc IN
ARC DS II ✅ ADOPTED 2026-09-19 (§3.7 second movement; §6 item 26, ALL FIVE clauses decided the same day) —
        the authored step. ✅ ALL THREE BUILT 2026-09-19 in the user's order — DS-17b (ranking was NOT
        enough: trusted_query is 9th of 10 under both orders, so the gated rows collapse behind a
        counted line; receipt taken live), DS-19 (authored SQL verified on SAVE, private to its chain,
        the predicted validator churn did not arrive), DS-18 (`synthesize`, its falsifier held, and it
        found a real defect in `check_grounding`). ✅ LIVE RECEIPT TAKEN on `baef6c3e`: broken SQL
        REFUSED at save (422), valid SQL stored as a `query_id` with no sql at rest, the minted row
        invisible to the catalogue and self-approved under the identity-off posture, and the chain's
        synthesis grounded in all four of its query's figures. The live run found the last defect —
        a test double looser than `LLMProvider.complete`.
        Measured the same day: `trusted_query` ships at palette weight 90, below the fold and dimmed
        (0 trusted queries on every connection but `workspace`); it names a `query_id`, never SQL; and
        nothing carries rows to a write-up (`investigate` binds only `question`, and this plane has no
        interpolation). Waves: DS-18 `synthesize` — write up the step before, under context authored on
        the node, with every number grounded in its input · DS-19 SQL a person authored, verified on SAVE
        through the trusted-query door, PRIVATE to its chain with a Promote door (item 26 (c), the user's
        call against the recommendation — visibility is a product question, custody a governance one, and
        only custody was at risk: one store, scope a flag, promotion a flag flip). The `sql` field is
        human-only, because the Investigate node is already the governed path where a model writes SQL.
        DS-17b ranks the palette by what this deployment can actually run — item 26 (e), taken SEPARATELY and
        first at the user's direction, because it is a defect and the other two are features: a gated kind
        currently sorts as if it were available, which is how `trusted_query` shipped and read as absent.
ARC IN  ✅ ALL FOUR WAVES MERGED #531 (`2ae9ae9d`) 2026-09-20 — the install. Built in the order
        IN-4 → IN-1 → IN-3 → IN-2, NOT the order drafted: IN-4 has to come first, and the
        decisive reason is sharper than atomic-swap. 102 files under `data/` are git-TRACKED and
        the running app writes several of them (`data/metrics.json` is dirty ON PURPOSE on the
        builder's own install), so a naive `aughor update` dirty-check refuses FOREVER on every
        install that has been used.
        IN-4 ✅ the data home: nothing moves until `aughor migrate-state` verifies a copy and
             writes its marker — a default that relocated on a directory's mere presence would
             make 1.4 GB of connections, history and receipts INVISIBLE rather than missing. A
             SPLIT, not a move (`AUTHORED_ENTRIES`, measured against `git ls-files data/`). Four
             path conventions reconciled at `resolve_db_path`, ~20 lines rather than 55 edits.
             🔴 The Fernet key had NO path override, computed twice from anchors a different
             number of `.parent` hops apart: state moving without it would have made every stored
             DSN undecryptable, silently, because resolving to an empty path GENERATES a key.
        IN-1 ✅ `aughor doctor` (typed verdict per check; no model call, no warehouse query, and
             it writes nothing — the obvious route opens `org_llm.db` and becomes a second writer
             on `data/`) · `aughor update` (fast-forward, refuse, NEVER reset) · `migrate-state`.
             🔴 Found by doctor's first live run: `aughor up`'s port guard had NEVER fired here.
             `_port_in_use` bound `127.0.0.1` with SO_REUSEADDR, which does not stop a WILDCARD
             listener — and `0.0.0.0` is how the runbook starts this API.
        IN-3 ✅ retries, a blobless-clone fallback, a preflight that warns and never blocks, and a
             TLS-proxy hint naming what Python AND Node each need — on BOTH installers, with
             `test_installer_parity` making the Windows twin falling behind a build failure.
        IN-2 ✅ the README's install section, written from measurement, with a guard asserting
             every command it shows resolves. WSL2 is NAMED and NOT CLAIMED (§6 item 25 (e) asks
             for a measurement nobody has taken); item 25 (d)'s short address is not invented.
        ⏳ Still owed: `migrate-state` has NEVER run for real — it needs the API stopped, which is
             the operator's, and until then every path resolves exactly as before, which is the
             design and not an omission.
             ✅ The overlay BUILT 2026-09-21 (branch `claude/roadmap-catch-up-535`, not merged): the
             catalogue's seed ships at `data/shipped/metrics.json`, this install's rows live in the
             ignored `data/metrics.instance.json`, and `data/metrics.json` is FROZEN — upstream never
             changes it again, so an install that wrote to it still fast-forwards. It is read once,
             in memory, and converted, verified, on the first metric write. `ontology_overrides/`
             gains a shipped seed layer (empty) and stays in the checkout. `glossary.yaml` split
             the same way the same day (seed `data/shipped/glossary.yaml`, instance
             `data/glossary.instance.yaml`; the generated sidecar stays where it always resolved).
             ⏳ Still owed from it: `context_graph/` and `ontology_column_config/` are tracked and
             rewritten by the app too — the same stranding, in other stores; and moving
             `ontology_overrides/` into the data home needs a verified top-up step, because an
             install that already migrated never received it.
             ✅ Closed in #535: `connectors/api/base_sync.py` resolves through `state_dir()`, whose
             env both hermeticity guards already carry, so `migrate-state` no longer leaves it
             behind · re-running `install.sh` / `install.ps1` on an existing clone fast-forwards it
             through the function `aughor update` uses — a refusal or an error is one line and never
             fails the install.
ARC JD  ✅ ADOPTED 2026-09-21 (§3.20; §6 item 28 — JD-5 BUILT on the user's flip the same night; JD-6 on HOLD); drafted 2026-09-17, recorded 2026-09-20 — the judgment seam: one state,
        N independent typed questions, a closed answer space, and a probability our code bands on.
        ✅ MERGED #535 (`583c8d9f`) 2026-09-21: JD-4 the instrument · JD-1 the seam (wired into no
        production path; its probability is STATED, not measured) · JD-3 the banded cascade (OFF,
        `semops.banded_cascade`) · JD-2's three survivors · A3 the definition-report screen · A5 the
        decision budget. ✅ JD-3's receipt TAKEN 2026-09-21 — falsifier did not fire (2 holds, 1 inconclusive with banding
        more accurate; the cheap and champion tiers are one model here) — then SLIMMED the same night (0.58× the request,
        banded ≈ 0.92× sampled total tokens, re-cost) and the token objection closed. ✅ JD-5's receipt TAKEN LIVE
        2026-09-21 (`docs/JEV_LIVE_RECEIPT_2026-09-21.md`): Jev beats production +2.6 (CI +1.1 to +4.2) at zero champion
        calls, 2.6× cheaper, passes the shuffled-context control — VERDICT KEEP. Then the user: "Flip the flag on and
        build the Jev binding" — JD-3 GRADUATED to default-ON (sampled cascade = the kill switch) and JD-5 BUILT
        (`aughor/judgment/jev.py`: flag `semops.jev_cheap_tier` OFF by default, PII withholds whole bundles, outbound
        seam counts every call, house-tier fallback so an outage is yesterday, never a champion flood; smoke-tested
        live end-to-end). pg-jev examined, not adopted. ⏳ JD-1's and JD-4's corpus receipts are still model calls. JD-4's first run
        took no reading on three of five measures; the floor is `choice_prior` 44.8%.
        ⚠️ The numbers are NOT the ones the draft asked for: it was
        written on an unmerged branch claiming §3.19 / item 25, which Arc IN took the same day, so it
        renumbers here and Arc IN is untouched — and item 28 therefore follows items 26 and 27
        (2026-09-19) while predating them. Measured 2026-09-17: the deep path is ~100% phase-serial LLM
        calls (373 s vs 304 s = 1.23×, 14 calls both arms); intake is ONE decoder call of 28 fields, ten
        of them pure judgments; semops batches 25 rows per prompt and escalates all 200 on a sampled 20%
        disagreement; `earned_confidence` is computed, never asserted. Waves: JD-4 the instrument FIRST
        (ECE + a shuffled-context control) → JD-1 the seam over our own providers → 🛑 JD-2 REFUTED
        2026-09-20 (`8797dfef`): 1,833 of 1,835 intake picks — 99.9% — were names the model was shown,
        so a closed option list removes a failure that is not happening; the retracted ~20% (`5176820e`)
        measured warehouse drift → JD-3 bands, not batches, in the cascade → JD-5 the hosted Jev binding
        (HOLD — 67.8% against Opus 5's 73.1% on the vendor's own benchmark; speed and cost, not
        accuracy) → JD-6 a local one-pass scorer (HOLD, pre-filter only). Alignment movement, from the
        +1 study 2026-09-19: ✅ A1 an outcome that can come out negative BUILT (`e68beffa`) —
        attributable 0 → 8 on `ask.route`, 0 → 5 on `converse.tool`, but confidence 1.00 on all 8, so
        A2 has no usable ranking signal yet · ✅ A4 the frozen-population rule BUILT (`407f0a4c`) —
        LuxExperience's refund breach 23.27% → 25.41% once 4,199 impossible rows stop counting as kept
        · ⏳ A2 (JD-1's seam exists; now waits on a site that yields a probability at all —
        `converse.tool` never does) · ✅ A3 · ✅ A5 (#535) · 🛑 A6 HOLD until ~150 labeled decisions.
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
        → ON-3 instances + the standard object view (FIRST SLICE 2026-09-11: object pages live, key
        links in answers, the receipt met end to end on a declared action) → ON-4 actions on
        objects with the overlay merged into the next answer (FIRST SLICE 2026-09-11: the receipt met live —
        an agent-proposed, human-accepted flag read back with its provenance) → AMENDED 2026-09-11 from
        the Fabric IQ study (§3.15): ON-3b the entity-type map · ON-3c the agent reads the type (BOTH FIRST
        SLICES 2026-09-11: the map, the measured display property and the path finder live on
        LuxExperience; describe_entity returns the type and the agent called it live through /ask) · ON-1b
        bindings, each property knowing its source (FIRST SLICE 2026-09-11: payments and shipments bound on
        LuxExperience's Order, each measured one row per order; l09 and l05, refused by ON-2, compile through
        them and equal their references) → ON-5 functions and model bindings, TIMESERIES PROPERTIES
        FIRST — ✅ BUILT AND RECEIPT MET 2026-09-12: a timeseries binding is reduced to each object's
        latest row (O5's semiadditive `last` declaration instantiated, its first caller); price_history
        bound on LuxExperience's Product reads €246.00 as of 2024-02-26 with its five readings behind it,
        and "products whose latest price > €500" compiles to 1,744, equal to its reference. The map was
        re-laid the same day on the user's reading of it (ON-3b). ON-6 (the context layer reaches the
        model) RETIRED 2026-09-11 — ON-0's falsifier fired on both blocks (§6 item 15).
        → SECOND MOVEMENT, adopted 2026-09-12 (the user: "integrate this in the main roadmap and take on
        seven first"): ON-7 the declared entity, its parts (a `detail` binding kind) and declared links —
        ✅ MERGED #494 2026-09-12 (receipt: Lux as 8 business entities from 14 tables, no model call) →
        ON-7b the explorer maps the business first (proposals with model provenance, measured, confirmed
        in the map) — ✅ FIRST SLICE + RECEIPT 2026-09-13: Lux registered again, 8 business entities drafted
        from 14 tables in one call, 4 of ON-7's 5 queries equal their references, the falsifier FIRED once
        (tickets under Order) so it stays on demand → ON-9 processes and promises — ✅ FIRST SLICE + RECEIPT 2026-09-13: Olist
        order-to-delivery declared and counted through the object door (dispatch broken on 9.35% of lines, delivery on 8.11% of
        orders, every count equal to its reference), the late segment, breach rate and lag derived by construction, 16/16
        guard mutations caught → ON-10 the investigation starts from the
        ontology (frame_question before the intake parse; the falsifier is a set where raw FAILS because
        the definition is not in the data) — ✅ FIRST SLICE 2026-09-13: framed with no model before the intake, 15 of 18
        Olist questions framed live through the door and none of the controls, the falsifier set of 15 executed, 29/29
        guard mutations caught; the falsifier HELD (framed 8 of the 12 declared-definition questions, raw 3, no control
        lost) and HELD AGAIN on LuxExperience, held out (framed 9 of 13, raw 1, one loss, no control lost); its matcher
        gaps fixed on a new set (51 of 51 in scope) → ON-8 one
        ontology, many sources (org-keyed, bindings name
        their connection, cross-source links via the foreach engine) — ✅ FIRST SLICE 2026-09-14: the organisation's
        ontology served from its declarations, a type or a static binding on any connection measured across two under the
        verdicts one connection meets, a to-one link or static binding across connections read by key and the answer
        aggregated in an in-process stage — every cross-source query equal to the single statement on a split warehouse,
        41/41 guard mutations caught; live on LuxExperience (two registrations of one file) every declaration counted
        across two equal to one connection's and five queries equal to the single statement, 1.4–5.2 s across against
        43–66 ms as one statement — about 30 ms per 1,000-key read. Order after ON-7 is the user's knob.
        → LEFTOVERS II (2026-09-15, `claude/on-leftovers-ii`): the cross-source security gate, cut reads known to be cut,
        typed values and bounded reads on every connector, reads past a type read by key, and to-many links, EXISTS,
        timeseries and detail bindings across; §6 item 18(b) decided — Shipment and Payment are entities with a link,
        applied live on LuxExperience.
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
- 🔴 **The playbook's outcome loop is COMPLETE, REACHABLE and starved — and the thing starving it is a field
  name.** Re-measured end to end 2026-09-19, and the first four answers were all "already built": `log_outcome`
  persists a `RecOutcome`, `update_playbook_success_rates` recomputes `wins/total` onto every entry and even
  promotes a draft at ≥2 outcomes and ≥50%, `retriever.py` already ranks by the learned rate and renders
  *"[no outcome data yet]"* when there is none, `POST /investigations/{id}/recommendations/{i}/outcome` serves it,
  `web/lib/api.ts` calls it, and **two components render the affordance** — `RecommendationInbox` (the top-level
  **Inbox** tab, fully reachable) and `ReportView`. Live content exists too: 7 of 12 real reports carry
  recommendations, 14 in all. `data/recommendation_outcomes.json` has never existed.
  🔴 **What was actually broken:** the neighbouring EXECUTE path read `report["recommended_actions"]` and each
  item's `text`. Every stored report carries **`recommendations`**, keyed `action` · `expected_impact` · `owner` ·
  `timeline` — measured over the live history, ALL use the first name and NONE the second. So `rec_text` fell
  through to the placeholder *"Recommendation #N from investigation X"*, wrapped in a bare `except Exception:
  pass`, and that placeholder was dispatched to the trigger **and handed to the departure gate as its `text`**.
  🔑 **HB-2 law 1 was therefore asked about a sentence containing no magnitudes, and passed. A recommendation full
  of numbers departed past a gate that never saw it** — the guard passing for the wrong reason, on the same day
  three other instances of that shape were found. ✅ **Fixed 2026-09-19**: the extraction is now a named function
  (`actions.recommendation_text`) because the bug was untestable where it lived; the older field stays a fallback;
  a negative index no longer wraps to a different recommendation; the swallow is a counted `tolerate`; and a
  placeholder that does depart is logged. 11 tests, four mutants killed including the original bug.
  ⏳ **Still open, and now genuinely the question:** nobody has ever recorded an outcome, on a loop that works.
  That is a product question — when is a person asked — not a missing mechanism.
  **The original entry, kept because its measurement stands:** live 2026-09-19:
  **878 entries, all active, `historical_success_rate` = 0 on every one of them** — so §6 item 20's
  *"the playbook ranks its entries by success rates learned from outcomes"* is inert, and the `provenCount`
  the panel computes has never been anything but zero. `owner_role` is the same defect one column over:
  **"Data Analyst" on all 878**, a field that reads as information and carries none. Found while moving the
  playbook off the nav (below) — the move is why anybody looked.
  🔑 This is §7's complete-and-inert shape, and the reason it survived is worth naming: the panel hides a
  zero rate per row (`{e.historical_success_rate > 0 && …}`), so a screen full of blanks looked like a screen
  of plays that simply had not been proven yet, rather than a loop that never ran. **An honest per-row
  default concealed a systemic absence.** Fixing the loop is a real build — where an outcome is recorded,
  what counts as one, and how a play is credited — and it should not be started by inferring the design from
  a zeroed column.
- ✅ **The playbook left the navigation, 2026-09-19 (the user's call: Settings ▸ Organization).** A nav door
  promises a room worth entering, and the measurement said otherwise: of 878 rows, **486 (55%) are
  data-quality rule-outs the Verifier runs inside a deep report** — never a decision a person takes — and the
  two columns that would have made the rest browsable were the constant and the blank above. It now sits
  beside INDUSTRIES, which is the only lever a person has over it: its entries arrive from the industry
  packages this organisation installs. The rule-outs are filtered from the default view and COUNTED in it,
  and a search for them still reaches them — a row somebody named must never be behind a fold (DS-17b, one
  screen over). The tab id survives, so ⌘K and any saved link still work.
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
> **Amended 2026-09-11 (later):** item 16 (exporting the measured ontology to Microsoft Fabric IQ)
> arrived with the Fabric IQ study and is **OPEN, not scheduled** — recorded so it is asked on purpose
> rather than drifted into. One open.
> **Amended 2026-09-12:** item 17 (Arc MT dropped — identity buys nothing where this actually runs)
> arrived and was decided in the user's own sentence. Item 16 is still the only one open.
> **Amended 2026-09-12 (later):** item 18 (the second movement's three shape questions) arrived with
> the movement's adoption and is **OPEN, with recommendations** — none blocks ON-7. Two open: 16, 18.
> **Amended 2026-09-13:** item 19 (Instrument, the design system) arrived with the Claude Design handoff; its
> three questions were asked before the build began and decided the same turn. Still two open: 16, 18.
> **Amended 2026-09-14:** item 18(a) — ON-8's scope key — was taken as recommended when ON-8 began; (b) and (c) stay
> open. Still two open: 16, 18.
> **Amended 2026-09-14, later:** item 20 — the user's two rules on an organisation's ontology and the explorer's
> reach, and the three questions they raised, answered the same turn. Still two open: 16, 18.
> **Amended 2026-09-15:** item 22 — Arc SP's second movement, authoring by sentence — arrived with the measured
> trace of the user's own Spotlight turn; clause (a) was answered yes the same turn and SP-7 began. (b), (c) and (d)
> stay open with recommendations, and none blocks SP-7. Open: 16, 18, 22(b–d).
> **Amended 2026-09-16:** 22(b) was decided with SP-10 ("Go for SP-10" on the both-recommendation), and 22(d) with
> SP-M's numbers on the table (graduate after the richer-fixture re-record). Open: 16, 18(c), 22(c).
> **Amended 2026-09-15, later:** item 18(b) — Shipment and Payment — decided by the user, and not as recommended:
> entities with a link, applied live on LuxExperience the same day. Open: 16, 18(c), 22(b–d).
> **Amended 2026-09-16:** item 24 (Arc HB — the hub) arrived at the user's *"Create a roadmap now"*; its shape was
> decided in the user's own sentences the day before and is recorded in the item so it is not re-asked, and the seven
> calls the build needs are open with recommendations. Open: 16, 18(c), 22(b–d), 24.
> **Amended 2026-09-16, later:** item 24 (a), (b) and (d) decided on the user's *"Lets take the logical next step..
> go.."* — §3.18 active, HB-1 first, `domain` grant-bearing, Viewer/Editor/Owner the first personas; (c) waits for
> HB-6, (e) for HB-3, (f) holds on the OAuth client, (g) rides the arc. Open: 16, 18(c), 22(c), 24(c·e·f·g).
> **Amended 2026-09-16, HB-6:** item 24 (c) decided on the user's *"Start hb-6"*, on the recorded recommendation —
> packs ship function groups; (e) had been taken with HB-3 the same day. Open: 16, 18(c), 22(c), 24(f·g).
> **Amended 2026-09-19:** item 26 (Arc DS's second movement — the authored step) arrived from the user reading the
> Automations palette, and is **OPEN with recommendations**; the measurement behind it corrected the premise (a SQL
> step ships, dimmed and below the fold) and separated a person authoring SQL from the two things the no-code law
> actually refuses. Open: 16, 18(c), 22(c), 24(f·g), 25, 26.
> **Amended 2026-09-19, later the same turn:** item 26 (a)–(d) answered by the user — adopted with DS-19 first,
> verification always and approval on the identity posture, a chain-private query with a Promote door (NOT as
> recommended), and `sql` never model-filled. Only (e), the palette's ranking, stays open, and it was never put
> to them. Open: 16, 18(c), 22(c), 24(f·g), 25, 26(e).
> **Amended 2026-09-19, same turn:** 26 (e) decided too — the palette ranking is taken SEPARATELY and first, as
> DS-17b. Item 26 is closed whole. Open: 16, 18(c), 22(c), 24(f·g), 25.
> **Amended 2026-09-20:** item 28 (Arc JD — the judgment seam) is recorded three days after it was
> drafted. It was written 2026-09-17 on the unmerged branch `origin/claude/fervent-cori-w9ogfc`
> (`93112558`) and it claimed **§3.19 and item 25** — both of which Arc IN, drafted the same day, had
> already taken on main. Arc JD renumbers to §3.20 / item 28 and Arc IN is untouched. **So item 28 sits
> after items 26 and 27, both decided 2026-09-19, although it predates them by two days:** this
> register is ordered by the number a thing was given, not by the day it was written, and every item
> carries its own drafting date for exactly this reason. Its clause (b) arrives **already refuted** —
> measured on the branch that recorded it, not on a later date — so it is stamped 🛑, not left reading
> as an open recommendation. Open: 16, 18(c), 22(c), 24(f·g), 25, 28(a·c·d·e·f).
> **Amended 2026-09-20, later:** item 29 (a measurement that refutes its own number does not leave)
> arrived from A4's receipt and was decided in the same turn. Open: 16, 18(c), 22(c), 24(f·g), 25,
> 28(a·c·d·e·f).
> **Amended 2026-09-21:** every open item put to the user and answered in one sitting. 16 REFUSED, not deferred
> (§4.6). 18(c) neither host offered: theLook, the live warehouse, is the go-to connection. 22(c) Accept stays the
> arming. 24(f) email holds for the OAuth client; 24(g) §0's amendment adopted. 25(a) stamped as shipped, and (c),
> (d), (e) offered and not chosen. 28 adopted — (a), (c), (f) — with JD-5 and JD-6 on hold. **The register is back
> at zero open.**
> **Amended 2026-09-22:** item 30 (Arc CB — the company brain, from the Codos idea set) arrived at the user's
> *"consider & plan"* and was answered in the same turn, four clauses; §3.21 drafted on those answers. Zero open.
> **Amended 2026-09-22, later:** item 30(a) REVISED by the user — foundations first (dated facts, the acceptance baseline, then owners), after the builder's "is this overdone?" reading was ruled to have measured the dev instance and not the design; CB-1 started.

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
16. ✅ **DECIDED 2026-09-21 (the user) — REFUSED: no export of the measured ontology to Microsoft Fabric IQ (§4.6).**
    Arrived with the Fabric IQ study (§3.15, "Amended 2026-09-11"). Fabric's ontology item wants what
    Aughor measures and Microsoft's own playground export drops: object types with a verified key and a
    display property, properties bound to their source columns, relationships with a cardinality, and ids
    that stay stable across exports (ON-1's api names). For a customer already on Fabric it is a door — an
    ontology Aughor built and measured, landing where their Fabric data agents read it — and it is also a
    question of what leaves the platform, against §0's thesis that the ontology→agent loop is the moat. It
    is not a second ontology store (§3.15's not-ported list): an export writes a definition and keeps
    nothing. An RDF/OWL export is the same question at lower demand.
    **(a)** Build an export door at all? **(b)** If yes, only after ON-1b (bindings are what it exports)
    and once Fabric's published item-definition format is verified against Microsoft's documentation — the
    playground's `fabric.ts` is a community implementation, not a contract.
    *Recommended: not now; revisit when a customer on Fabric asks, with (b)'s preconditions.*
    **The user refused it outright rather than defer, 2026-09-21** — recorded in §4.6 so it is not re-proposed
    without new facts.

17. ✅ **DECIDED 2026-09-12 — Arc MT is not the next build, and not while this runs locally.** Asked what
    followed ON-5, the recommendation was MT-0 + MT-1 (§3.12's own "next"). The user: *"MT-0 and MT-1 make no
    sense if this is not hosted somewhere. Locally, I don't need it. And worse is not working as expected due to
    backend compute and storage limitations."* Identity and per-user tenancy earn their keep only on a hosted
    deployment, and the hosted one does not work well enough to be where the value is — so the wave buys nothing
    where the platform actually runs and every receipt is actually taken. Recorded here because it reverses a
    documented "NEXT BUILD", not because it was contentious: the spec stands, unrefused, waiting on the user
    saying hosting matters. The signal was there a month earlier — MT-2 was keyed on a Google OAuth client the
    user never created — and was read as waiting rather than as not wanted.

18. ✅ **DECIDED — the second movement's shape questions, all three answered ((c) 2026-09-21).** Arrived with the
    adoption of ON-7…ON-10 (§3.15, "Amended 2026-09-12 — the SECOND MOVEMENT"). The user fixed the order's
    head (ON-7 first) and added ON-7b; three shape questions remain, each with a recommendation:
    ✅ **(a) The scope key for ON-8 — TAKEN AS RECOMMENDED 2026-09-14.** The organisation, or a named DOMAIN inside it
    (one company may hold a retail ontology and a finance ontology). *Recommended: a named domain, defaulting to one per
    organisation — the key is `org/domain`, and a single-domain org never sees the second segment.* The recommendation was
    put to the user before the build, and they answered *"Lets go with ON-8 then.."*: the key is `org/domain`, the domain is
    `default` until an organisation names another, and a door names one with `?domain=`.
    ✅ **(b) DECIDED 2026-09-15 (the user) — entities with a link, not as recommended.** Asked with the leftovers of
    the arc (*"Entities with a link"*). The question was: Shipment and Payment, PARTS of Order, or entities of their
    own with a link? Both had been static 1:1 bindings on Lux's Order (ON-1b) and parts of it (ON-7). *Recommended
    was parts — the business speaks of an order's payment and an order's shipment; a shipment becomes an entity only
    where the business ships across orders (consolidated freight), which a measured N:N key would show.* **Applied
    live on LuxExperience (`914df862`), through the doors, no model call:** Shipment and Payment released from Order;
    `Shipment fulfils Order` (reverse `shipment`) and `Payment pays_for Order` (reverse `payment`) declared and
    measured 1:1, every key held; Order's `shipments` and `payments` static bindings withdrawn; `order_to_shipment`
    re-declared on `shipment.ship_date`, its counts unchanged (107,903 reached, 0 broken, 4,536 open, 4,528 overdue as
    of 2025-06-30; p50/p90/p95 0/1/1 days); a measure pass left every process and rule verified; seven questions
    that read the two tables — shipping cost by carrier, payment by method, delivery days by service level, orders
    by payment status, shipments by warehouse country, high-risk payments, orders shipped from Italy — returned the
    same rows through the links as they had through the bindings. The map shows ten cards where it showed eight.
    The explorer's registration (`b428fce7`) and the organisation's `default` domain keep their own declarations.
    **(c) The host for ON-9/ON-10's receipts** — *(2026-09-13: ON-9's receipt was taken on Olist, as recommended;
    LuxExperience hosted the never-broken flag instead. ON-10's falsifier was written and run on Olist too and held
    (2026-09-13), and held again on LuxExperience through rules and a refund process declared live there with no
    generator change, so the question stays open for the pack enrichment only; framed on LuxExperience, the dispatch
    question reads as a shipping
    promise the data never breaks — the case for the pack enrichment, now visible on every framed answer.)* —
    Olist (`baef6c3e/ecommerce`, real delays: 9.35% late
    dispatch, 8.11% late delivery) first, or enrich the LuxExperience pack's generator with realistic
    dispatch lags so the demo pack can host the question. *Recommended: Olist first — no generator change,
    real data; the pack enrichment follows as its own small, deterministic change so the demo can tell the
    story.*
    ✅ **(c) DECIDED 2026-09-21 (the user) — neither: theLook.** Asked whether to enrich the LuxExperience
    generator, the user answered *"thelook should be the go-to connection as it updates daily.."* — so these
    receipts, and a demo of them, are hosted on a live warehouse rather than on a frozen dataset or a generator,
    and the Lux generator is not changed. ⚠️ theLook keeps rewriting its most recent days (measured earlier: its
    counts are a function of a row's age), so a receipt taken there states its as-of date and leaves the
    unsettled window out.


19. ✅ **DECIDED 2026-09-13 — Instrument (§3.16): what the first pass covers, and the two places the design met a
    measurement.** Asked before a line was written, because each answer changed the build.
    **(a) Scope** — tokens, type, motion, the primitives and the shell chrome; no new features (not the activity
    strip or the Human / Agent / Substrate switcher, not the trust system as primitives).
    **(b) The design's chart hues failed `lint:palette`** — dark: the lightness band on three hues, the chroma floor,
    and the normal-vision floor at ΔE 15.0 between green and blue; light: the chroma floor; and `--chart-7 =
    --chart-3` fails the separation that keeps the automation canvas's seven kinds apart. *Adjust the hues to pass*:
    charts stay the intent hues, each failing hue moves the minimum the validator needs (the largest, dark amber,
    ΔE 4.3), and `--chart-7` stays a separately validated accent.
    **(c) The design's `--t3`/`--t4` are dimmer than the ramp they replace** (dark t4 from about 3.7:1 to 2.8:1) while
    `--t4` was a text colour in 425 places. *Take the design's ramp and move every text colour off `--t4` to `--t3`*;
    `--t4` keeps ticks and rules. The content-side fix the user chose for Agent Ops on 2026-08-22, made platform-wide.
    All three recommendations were taken as written.

20. ✅ **DECIDED 2026-09-14 (the user) — an organisation's ontology is edited by people only, and the explorer does not
    look beyond the connection it explores.** Set in the user's words after ON-8's first slice: *"The out of the
    connection ontology should be strictly human edit. The Explorer agent should not look beyond a particular
    connection."* An audit of the explorer's run path found that it already did look beyond: autoseed wrote every
    connection's model-written table descriptions into ONE global glossary map, read back for any table of the same
    name; the schema text, the coherence gates and the catalogue build read the metric registry with no connection; a
    federated connection opens its members; and the playbook ranks its entries by success rates learned from outcomes on
    every connection. The organisation's ontology itself was never read by the explorer. Three questions followed and
    were answered the same turn, each as recommended:
    **(a) The glossary** — a model's words are written in the section of the connection whose tables it read; a
    connection reads a person's global words and its own section; a model-written global entry names no connection, so
    none reads it until autoseed writes it again for the connection that does.
    **(b) A federated connection** — not explored; whoever starts an exploration on one is told why.
    **(c) The playbook** — the explorer ranks entries by relevance alone; investigations keep the learned rates.
    The curated KB, the industry KB, organisation settings and pack claims stay: product and organisation knowledge, not
    another connection's data. **Held by:** the store's own writer for an organisation's tree
    (`overrides.save_organisation_override`, which writes a person's declaration only — every other writer refuses the
    scope); a router dependency on the ontology and object doors that refuses the tree's segment as a connection id, and
    the web's `domain:` scope on any door that takes no `?domain=` (the explorer's doors take none); a declaration that
    says it is a model's refused at the domain doors; a copied column profile that keeps what was measured and never
    words (`bindings.PROFILE_COPIED`); the metric registry read per connection (`build_metrics_block`, the drift gate and
    the label vocabulary, `builder._lift_metrics`); the glossary read in one connection's layers
    (`glossary._connection_layers`) and written in its section (autoseed, the sidecar split); `explorer_refusal` on every
    spawn path; `learned_rates=False` at the explorer's playbook read; and an import-and-call ratchet
    (`tests/unit/test_organisation_ontology_boundary.py`) that names who may import the organisation's ontology and its
    writer, what the explorer may not import, and that every prompt read of the glossary names its connection.
    **Receipts** (commit `9d2592ff` on `claude/on-8-many-sources`): the ratchet above, `tests/unit/test_explorer_reads_one_connection.py`,
    and new cases in `test_object_sources.py`, `test_ontology_o2_rekey.py` and `test_formula_drift.py` — the targeted
    runs green (962, then 85 on the exploration doors); **50 guard mutations, every one caught** (29 on the
    organisation's ontology and the metrics, 19 on the glossary, federated connections and the playbook, 2 on the canvas
    doors, which also refuse before they wipe). **Live, 2026-09-14,** the API restarted on the commit (0 active jobs;
    the three saved canvases already finished, so nothing resumed): the tree's segment as a connection id, the explorer
    on the web's domain scope and a declaration marked as a model's each answered 400 with the reason, and nothing was
    written; LuxExperience's `default` domain still maps Order and Customer across its two registrations with the
    cross-source link, and Order's 26 properties keep their roles and carry no copied words. **What the glossary call
    costs:** the sidecar held 264 model-written global entries (182 qualified, 82 bare) and no connection's section, so
    no connection reads any of them now — Olist's schema text no longer carries the generated `orders` description —
    until autoseed writes them again per connection, one model call per undescribed table, on each connection's next
    intelligence build. The full backend suite ran once on the commit: **10,020 passed, 5 skipped**.

21. ✅ **DECIDED 2026-09-14 (the user) — Arc IP (§3.17): nine answers that shape the industry packages.** Put as the
    plan's open calls, each with a recommendation, and answered over two turns.
    **(1) Skipping the install question** — every shipped package stays available and the industry is detected per
    connection. *As recommended.* **Built 2026-09-17 (IP-2):** Enter, no terminal, or no file all keep every package;
    a skip is recorded as `null` so the installer does not ask again.
    **(2) Where packages live** — in the repo; no registry. *As recommended.*
    **(3) Which industry goes first** — left to the builder: **banking & lending**, then payments & fintech, then
    insurance.
    **(4) Healthcare brings patient data** — *not* as recommended: healthcare moves to tier 2, and payments comes
    forward into tier 1.
    **(5) The Briefer reads the recipes** — yes. *As recommended.*
    **(6) A package's ontology claims** — measured on every connection of its industry, not only where a person bound
    the pack. *As recommended.*
    **(7) Existing playbooks and the 486 new plays** — not yet: they arrive when IP-1 routes data-quality plays to the
    Verifier. *As recommended.* **Delivered 2026-09-17 by IP-1:** the route is rule-outs on deep reports (the user's
    call when asked how the checks reach the Verifier — not repair hints measured first, not running the detection
    queries where tables match, not carry-only), and existing playbooks receive the 486 at startup, once, never
    resurrecting a check a person deleted.
    **(8) Ablation spend** — gate 5 for the reference package; later packages only where gate 4 is ambiguous. *As
    recommended.*
    **(9) Record the arc here** — yes: §3.17, this item and the §5 band.

22. ✅ **(a) DECIDED 2026-09-15 (the user) — Arc SP's second movement: authoring by sentence (§3.11).** The user asked
    whether agents and automations can be created in natural language, then drove the answer themselves — *"create an
    agent that delivers anomalies to slack every morning at 9am"* — and sent the transcript and a screenshot of the
    overlay: *"it is honest - which is nice"*, and the presentation *"must feel agentic"*. The trace (§3.11, second
    movement) found the drafts real and the path short of an agent that runs. Four clauses, each with the builder's
    recommendation:
    ✅ **(a) Adoption** — SP-7…SP-14, with SP-M alongside. *The user, verbatim: "yes add it to the roadmap and start SP-7".*
    ✅ **(b) DECIDED 2026-09-15 (the user) — both, as recommended.** Asked as "markdown renderer plus cards, or cards
    only" with the recommendation stated; the user answered "Go for SP-10" on it. react-markdown + remark-gfm carry
    the prose behind an allowlisted, designed surface (§3.11 SP-10); the cards carry the acts.
    ✅ **(c) DECIDED 2026-09-21 (the user) — Accept stays the arming, as recommended** — not a separate Arm step after Accept. *Recommended: keep it; with SP-7 Accept
    refuses while a choice is still open and the first run is stated, so a second click would add no check.* SP-7 is
    built on the recommendation; the call stays the user's.
    ✅ **(d) DECIDED 2026-09-16 (the user) — graduate AFTER the richer-fixture re-record, as recommended.** Asked with
    SP-M's first recorded numbers on the table (every staged draft honest, 10/10 with zero check failures; 21/30
    staged nothing on the SPARSE fixture, agent bundles 0/5 as stated refusals). The user chose the middle door: seed
    a richer fixture, re-record the thirty asks, and graduate when the STAGING rate looks healthy — not just the
    honesty rate. SP-14 ships right after. Until then a fresh install's Quick chip keeps saying that setting things
    up needs the conversation.

23. ✅ **DECIDED 2026-09-15 (the user) — the answer vocabulary (§3.11, third movement).** The user, with the Adaptive
    Cards catalog on screen: *"Why don't we consider introducing such UI elements? We have been calling ourselves
    Agentic forever without the very important UI elements that make it so."* The builder's assessment (the closed
    vocabulary + door-bound actions reading, the open-UI-DSL shape refused, waves AV-0…AV-M) was adopted in the user's
    own sentence: *"Add it to the roadmap and let's start working on it right away."* Rendered in the platform's own
    design system, never the Teams card aesthetic — the user's standing rule that chat feels like a frontier-LLM
    conversation points the same way.

24. ✅ **DRAFTED 2026-09-16 (the user: "Create a roadmap now") — Arc HB, the hub (§3.18): the shape decided in
    conversation 2026-09-15; (a), (b) and (d) DECIDED 2026-09-16, (c) and (e) that week, (f) and (g) 2026-09-21 —
    every clause decided.** Decided in the
    user's own
    words, recorded here so they are not re-asked: the nomenclature does not change — the airport stays an analogy;
    the four people were examples, and the mechanism serves every layer with no layer taxonomy; personas as
    platform-shipped groups carrying a level per securable kind, and the organisation's functions as groups of users
    (people and agents) — the Databricks workspace shape on our own `Grant` seam; and the definition — people still
    come to the platform, and it also receives data and exports information, intelligence and analysis.
    **(a) Adoption — ✅ DECIDED 2026-09-16 (the user: "Lets take the logical next step.. go..", on the recorded
    recommendation): §3.18 is active, HB-1 first** — the routing half, which has value with identity off; HB-2/HB-3
    need owners and subscribers to send to.
    **(b) `domain` becomes a grant-bearing tag** beside `tier` and `pii` — **✅ DECIDED 2026-09-16 with (a)**, being a
    call HB-1's own spec names (grants by tag are what make a function group self-maintaining); tags stay human-set,
    so a tag cannot be granted by a model.
    **(c) Packs ship function groups** — the group, its tags, its default grants, subscriptions and automations —
    **✅ DECIDED 2026-09-16 with HB-6 (the user: "Start hb-6", on the recorded recommendation).** Two spellings the
    build fixed: "tagged" is subscribe grants on the pack's domains, because a group is a principal, not a securable
    — (b)'s grants-by-tag mechanism is what makes the group self-maintaining; and a pack automation lands declared
    (`pack:<id>`), on probation and DISARMED, so nothing a pack ships acts before a person arms it. A re-install
    never takes back what operators set (the group's channel, its members, an arming, a graduation).
    **(d) The persona set** — Viewer / Editor / Owner as the first persona groups; a Steward only when a deployment
    asks — **✅ DECIDED 2026-09-16 with (a)**, being the personas HB-1 ships.
    **(e) The first live receipt's host** — Olist's dispatch promise — **✅ DECIDED 2026-09-16 (the user: "Go for
    HB-3 entirely", on the recorded recommendation: real breaches, three new legs, no new channel).** One honesty
    note recorded with the decision: Olist is a FROZEN historical dataset, so the "number recovered" leg can prove
    its MECHANISM (re-measure at close) but the rate itself cannot move — the receipt reports that plainly.
    **(f) The email channel** — keyed on the Google OAuth client (VA-11); HB-5's email half waits for it.
    *Recommended: hold.* **✅ DECIDED 2026-09-21 (the user) — hold, as recommended**, until a Google OAuth client exists.
    **(g) The §0 amendment** as written — the hub as the platform's purpose, the three planes its infrastructure.
    *Recommended: yes.* **✅ DECIDED 2026-09-21 (the user) — yes; §0 carries it.**
    Not decided here because it isn't ripe: hosting and uptime (§6 item 17 stands — the hub exports only from where the
    platform runs); persona names beyond the three; row policies by group (HB-1's enforcement half, when identity is
    on).

25. ✅ **DRAFTED 2026-09-17 (the user: "Lets add this to the roadmap first.. I want to finish IP arc first though..")
    — Arc IN, the install (§3.19): ALL FOUR WAVES MERGED #531 (`2ae9ae9d`) 2026-09-20 — and (a) STAMPED
    2026-09-21, as shipped.** The arc shipped on the user's direct instruction ("just take it all in one go and
    finish the Arc"), which also overrode their own "finish Arc IP first" order. Recorded plainly rather
    than back-filled as an adoption: what follows are the recommendations as drafted, and (a) is now moot
    for sequencing but still unanswered as a decision. (b) the data home LANDED as recommended, planned on
    its own. (c) `--non-interactive` was NOT added — the industries question already stays off the
    unattended path, and nobody has measured a real Windows console. (e) WSL2 is named and not claimed,
    exactly as recommended. Open, each with the builder's
    recommendation:
    **(a) Adoption and order** — IN-1 and IN-2 first (cheap, low risk, real gaps), IN-3 beside them, IN-4 last with its
    own plan. *Recommended: yes, after Arc IP.* **✅ STAMPED 2026-09-21 (the user) — adopted as shipped.**
    **(b) A data home (IN-4)** — the state leaves the checkout. *Recommended: yes, planned on its own — it touches every
    store.*
    **(c) The industries question** — it stays in the install (§6 item 21, answer 1), now asked only where a person can
    answer, or it moves to the app's first run with `--industries` kept for scripts. *Recommended: keep it in the
    install, add `--non-interactive`, and measure it once in a real Windows console before calling Windows done.*
    **(d) A short install address** — it needs a domain the project owns. *Recommended: when there is one; until then
    the README shows the PowerShell-native form beside the Command Prompt one.*
    **(e) WSL2** — named as supported. *Recommended: measure the installer there first, then say so.*
    **(f) Not copied** — a portable Git Bash, Termux, a root multi-user install, the stage protocol, shell rc edits.
    *Recommended: not now (reasons in §3.19).*
    **Put to the user 2026-09-21: only (a) was selected.** (c) `--non-interactive` with a Windows-console
    measurement, (d) the short address and (e) measuring WSL2 were offered and NOT chosen, so none is adopted:
    the install stays as it shipped — WSL2 named and not claimed, no short address, no new flag.

26. ✅ **DECIDED 2026-09-19 (the user) — Arc DS's second movement, the authored step (§3.7): a `synthesize` node,
    and explicit SQL on the Trusted query step.** Drafted and answered the same day; (a)–(d) stamped in the user's own
    reply, and (e) in a follow-up the same turn. The user's two sentences are the spec:
    the component *"should say synthesize data output from previous node and context can be added in the current node"*,
    and Trusted query *"needs to be generally available for explicity SQL input by the user"*. Open, each with the
    builder's recommendation:
    ✅ **(a) DECIDED — adopted, DS-19 first, as recommended** (the user: *"Okay"*). The two are independent; the pair
    is what closes the user's sentence, and DS-19 gives DS-18 something worth writing up.
    ✅ **(b) DECIDED — as recommended** (the user: *"Agreed"*). Verification is always mandatory: a real execution plus
    the battery, on SAVE, never at 09:00. Approval follows the deployment's identity posture — recorded self-approval
    under the author's name while identity is off, a second principal once VA-10 is on. Requiring a second click from
    the only account on a local install is theatre, and theatre is how a gate stops being read.
    ✅ **(c) DECIDED — private to the chain, with a Promote door; NOT as recommended** (the user: *"Private in the
    chain with option to promote it later"*). The recommendation argued that a private copy is a second place queries
    live; the answer is better, because it separates two things the recommendation had fused. **Where a query is
    VISIBLE is a product question — a catalogue filled with one-off chain SQL stops being a catalogue — and where its
    CUSTODY lives is a governance one.** Only the second was ever at risk. So: private by default, promotable by one
    click, and still a row in the ONE trusted-query store with its own verification, stamp and audit, marked as owned
    by its automation and hidden from the picker. Promotion is a flag flip, not a data move. 🔑 The shape to refuse is
    a verification record stored on the step itself — that would be the second store the recommendation feared, and it
    is avoidable while giving the user exactly what they asked for. Cost, recorded on DS-19: `REQUIRED_CONFIG` for
    `trusted_query` becomes *exactly one of* `query_id` or inline `question` + `sql`.
    ✅ **(d) DECIDED — never, as recommended, and on a better argument than the one offered** (the user: *"Never -
    thats the whole point. Investigate node exists separately to form its own SQL, etc"*). The recommendation appealed
    to the no-code law; the user's reason is structural and stronger — **a node whose job is "a model writes the SQL"
    already ships, governed, spanned and grounded as such, so a second one carrying none of that machinery has no
    reason to exist.** The two nodes are not competing shapes of one idea; they are the model's path and the person's,
    and each is already whole. Guarded in `propose.py`, with a test that fails if a drafted or imported step carries a
    `sql` field.
    ✅ **(e) DECIDED 2026-09-19 (the user: *"take 26(e) separately"*) — the palette's ranking, as its own change,
    ahead of DS-19 and not folded into it.** A kind that is dimmed on this connection currently sorts as if it were
    available, which is how a shipped capability read as a missing one and produced this whole item. Taking it apart
    from DS-19 is the right call for a reason worth recording: **it is a defect, and DS-19 is a feature.** Folded
    together, the fix would ship only when the feature did, and its receipt would read "the new thing is visible"
    rather than "the thing that was always there is now findable" — which is the claim that actually needs testing, on
    the palette as it stands today. It also repairs the surface for `metric_value`, `mcp_call` and `integration_call`,
    each gated the same way and none of them waiting on DS-19.
    Not decided here because it isn't ripe: a Python node (refused, §4.1/§4.2 and `_NO_CODE_LAW`, and the user's
    "python or SQL" was answered by separating the three threats rather than by softening the law); an expression
    language on bindings (`dataflow.py:58` refuses it for the same reason).

27. ✅ **DECIDED 2026-09-19 (the user: *"go ahead with item 27"*) — a synthesis leaves the platform on the rows
    it was grounded in, both clauses as recommended; BUILT and DEPARTED the same day.** Found by building the
    first real chain on DS-18/DS-19. `trusted_query` → `synthesize` → `slack_post` runs green and is
    HELD at departure, permanently: HB-2 law 1 admits only a measurement built from an analysis or an alert, and
    a `synthesize` step publishes prose plus no measurement. So the step built to deliver a write-up "to Slack or
    practically anywhere" cannot deliver one, and no authoring fixes it.
    ✅ **(a) Add a `measurement_for_synthesis` builder beside its siblings in `govern/departure_basis.py` — values
    = the numbers in the rows the answer was grounded in, source = the trusted query, `remeasure` = re-run it?
    *Recommended: yes. It is the existing one-builder-per-source-kind pattern rather than an exception, and the
    warrant is stronger than the prose case it would sit beside: `check_grounding` has already proved every
    number in the answer appears in those exact rows, and DS-19 verified the query by executing it at save.*
    ✅ **(b) Should that basis require the query to be PROMOTED (in the connection's catalogue) rather than
    chain-private? *Recommended: no — scope is about who may SEE a query (§6 item 26 (c)), and a chain-private
    query is verified and approved exactly like a promoted one. Tying departure to visibility would conflate the
    two again, the distinction item 26 (c) was decided to keep apart.*
    Not part of this: law 2's approved-definition requirement, which held the same send because theLook's
    `units_sold` was a draft. An ordinary metric call, and the user made it the same turn — `units_sold`
    proposed and approved (v1), after which the gate's `definition` check reads *"cites metric units_sold v1"*.

---

28. ✅ **DRAFTED 2026-09-17 (the user: "find ways to improve our platform", after reading TypeSafe's Jev
    and the `jevlike` re-derivation); RECORDED 2026-09-20; ADOPTED 2026-09-21 — Arc JD, the judgment seam (§3.20): three
    adoptions that need no vendor, two that wait, and one that was measured and REFUTED before it could
    be built.** ⚠️ **This item is out of date order and deliberately so.** It was drafted two days
    before items 26 and 27 and takes a number after them, because it was written on a branch that never
    merged and claimed §3.19 / item 25 — numbers Arc IN had already taken the same day. It renumbers;
    Arc IN does not. The studies are `docs/TYPESAFE_JEV_STUDY_2026-09-17.md` and its +1,
    `docs/JEV_ALIGN_STUDY_2026-09-19.md`; the first states plainly which of its numbers are second-hand
    (`docs.typesafe.ai` and `typesafe.ai` are blocked by this environment's egress policy, so the
    vendor's own pages were never read — the API contract comes from a third-party client that calls
    it), and the second was read in full but **never executed**.
    **(a) The seam and the instrument (JD-1, JD-4)** — a typed `judge(state, questions)` call over our
    existing providers, and `jevlike`'s calibration battery (ECE + a shuffled-context control) as the
    standing guard on it. *Recommended: yes, and JD-4 first — it is the instrument every other slice is
    measured with, it would have caught ON-0's lift-that-wasn't, and clause (b) below is what happens
    without it.*
    🛑 **(b) Intake's judgments as typed questions, with closed option lists (JD-2) — THE PREMISE IS
    REFUTED; this clause is NOT an open recommendation.** As drafted, `date_column`, `metric_table` and
    `dimensions` became choices over the schema, which cannot name a column that does not exist,
    retiring a repair path that cost up to three sequential round-trips on the critical path of every
    investigation; *recommended yes, as monotonic by construction and therefore provable below the noise
    floor.* Measured 2026-09-20 against the schema block persisted with each run (`filtered_schema`, the
    one ground truth that cannot drift): **1,833 of 1,835 picks — 99.9% — were names the model had been
    shown** (`metric_table` 201/201, `date_column` 183/185, `dimensions` 1,449/1,449, over 202 threads /
    201 investigations, 29 Jun – 19 Sep), and 0 of 202 specs were rewritten mid-run. **The falsifier
    fires.** 🔴 The first measurement was wrong in the other direction and is retracted with its
    replacement: `5176820e` reported ~20% invalid picks by comparing three-month-old specs against
    today's `data/*.duckdb`, never opening the `local_upload` store that owns 140 of the 202 specs;
    `8797dfef` retracts it. Re-pointing per connection gave 46%, equally meaningless. Both numbers
    measured warehouse drift and called it model behaviour. ✅ What survives and is still worth doing:
    `dimensions` is validated nowhere, the `metric_table` correction retry is accepted without
    re-validation (`aughor/agent/investigate.py:5676`), and **no counter or event fires on a spec
    repair** — so the receipt this clause named for itself does not exist yet. *Recommendation as
    amended: fix those three on their own merits; do not build a closed option list to remove a failure
    this corpus says is not happening.* ✅ The three were fixed in #535 (§3.20).
    **(c) Confidence bands in the semops cascade (JD-3)** — spend the champion tier on the uncertain
    rows only, and route the band's floor to a person. *Recommended: yes, after (a).*
    **(d) The hosted Jev binding (JD-5)** — one backend behind the seam, off by default, behind the
    outbound grant and the PII gate, never on the verdict path. The state is customer row text leaving
    the box, and Jev's own benchmark puts it at 67.8% against Opus 5's 73.1%. *Recommended: hold until
    (a) exists and can measure it; adopt only for pre-filters and rankings where a wrong answer is cheap
    and recoverable.* ✅ **MEASURED LIVE 2026-09-21 at the user's direction** (*"prove me the value …
    if yes, we keep it; if not, we throw it out"* — the key entered the same evening): **it works, keep
    it** — +2.6 points over production at zero champion calls, 2.6× cheaper, control passed, ECE's
    miscalibration confined inside the escalation band; the binding itself stays unbuilt and the flip
    stays the operator's (`docs/JEV_LIVE_RECEIPT_2026-09-21.md`). `pg-jev` examined the same night and
    not adopted (Postgres-superuser-only surface; the seam already owns this ground). ✅ **And the
    operator flipped, in words: "Flip the flag on and build the Jev binding" — JD-3 default-ON, JD-5
    BUILT** (four gates, house-tier fallback, flag `semops.jev_cheap_tier` awaiting its live-deployment
    numbers; the hold on (d) is LIFTED by the user's own sentence).
    **(e) The local one-pass scorer (JD-6)** — sovereign, CPU-sized, trained on our own logged
    decisions, weights outside the installer. *Recommended: hold behind (a) and (d)'s measurement; it is
    a pre-filter, not a decider.*
    **(f) The alignment movement (A1–A6), added 2026-09-19 from the `jev-align` study** — the loop
    around the judgment, rather than its shape. ✅ **A1 (an outcome that can come out negative) and A4
    (a measurement carries its impossible rows) are BUILT** (`e68beffa`, `407f0a4c`), which is why this
    clause arrives with receipts and the JD series does not: A1 moved attributable decisions from 0 to 8
    on `ask.route` and 0 to 5 on `converse.tool`, and A4 moved LuxExperience's refund-breach rate from
    23.27% to 25.41% by refusing to count 4,199 impossible rows as kept. ⏳ A2 waits on (a)'s
    probability — and A1 measured that probability arriving **flat, 1.00 on all 8**, so (a) has to
    produce a usable one before A2 means anything. ✅ A3 and A5 BUILT in #535 (§3.20).
    ✅ **ADOPTED 2026-09-21 (the user), as recommended: (a) the seam and the instrument, (c) the bands and (f)
    the alignment movement — with (d) JD-5 and (e) JD-6 on HOLD, and A6 held on its number.** JD-4, JD-1 and
    JD-3 were built and merged in #535 before the stamp, the same shape as item 25 (a). Later the same day the
    operator spent the receipts that were waiting on their word: JD-3's (falsifier quiet; then the seam slimmed
    and the token objection closed at ≈0.92× — flag still OFF) and JD-5's, LIVE (verdict KEEP; binding still
    unbuilt). JD-1's agreement receipt and JD-4's corpus receipt remain unspent model calls.
    🛑 A6 (an optimizer over definitions) is HELD on a number: five verdicts, unchanged in sixteen days,
    is an optimizer on noise. 🛑 Refused outright: a label picker that pre-selects the model's own answer.
    Not decided here because it isn't ripe: whether a judgment's probability may ever reach a reader
    (today `earned_confidence` is computed from evidence and nothing else asserts confidence); and
    whether the uncertainty band's floor routes through the existing 428 approval gate or somewhere new.

29. ✅ **DECIDED 2026-09-20 (the user, after A4 showed the caveat travelling but not stopping anything)
    — a measurement that refutes its own number does not leave; BUILT the same day** (`7cd717e0`).
    §3.20's A4 put a promise's impossible rows on the measurement and carried them into `receipt_line`,
    and they departed anyway: a caveat qualified the number and never held it. It now holds. A new
    `caveat` guard sits beside `trust` in the departure gate, because both are accuracy holds about the
    figure itself rather than about who may receive it, and both are reached from the measurement
    instead of from the text. **Which caveats block is `departure_basis._blocking`'s call, not the
    gate's** — the gate asks the measurement, so it never has to learn a promise's vocabulary, and
    `Measurement.blocking_caveats` stays separate from `caveats` deliberately: collapsing them would
    turn "a caveat holds" into "every caveat holds", and a gate that blocks on every caveat teaches
    senders to stop writing them. "Never broken" still rides the receipt and still departs.
    ⚠️ **One thing the builder chose alone, and it is one line to reverse.** Three live promises carry
    impossible rows, not one — LuxExperience `return_to_refund/refunded` 23.27% → 25.41% (+2.13pp, 8.4%
    relative), theLook `order_to_delivery/dispatched` 9.35% → 9.47% (+0.12pp, 1.2%), theLook
    `order_to_delivery/delivered` 8.11% → 8.11% (+0.00pp, 0.0%). An unconditional hold would stop
    theLook's dispatch watch — the live send this module's own docstring cites as its anchor — over a
    tenth of a point, and the delivery one over nothing at all. So the blocking prefix is used only once
    the two readings disagree by more than the platform's OWN bar for that
    (`IMPOSSIBLE_LAG_MATERIAL_REL = 0.05`, equal to the deep run's `_METRIC_DIVERGENCE_REL`, with a test
    asserting the two stay equal); below it the same finding is stated in full under a distinct prefix
    that departs. **A rate that cannot be computed at all blocks, because unquantified is not the same
    as small.** To make the hold unconditional, delete the `moved >= IMPOSSIBLE_LAG_MATERIAL_REL`
    branch. Mutation-tested four ways — the guard never holding, every caveat blocking, nothing
    blocking, and the two prefixes sharing a stem — each killed by assertion; one of the builder's own
    A4 tests had been passing for the wrong reason (it asserted the impossible-lag caveat departs, which
    production can no longer do) and was rewritten. Suite 11,293 passed, 0 failed, pytest exit 0.
    `web/lib/departures.ts` carries the guard in both maps, verified by INSPECTION and not by running —
    that worktree had no `node_modules`.

30. ✅ **DRAFTED 2026-09-22 (the user: *"Once done, lets consider & plan for Codos roadmap items"*) — Arc CB, the
    company brain (§3.21): four answers that shape it, given before the draft was written.** (a) **Order — finish what
    exists first**, as recommended — **REVISED 2026-09-22, later, by the user: foundations first** (CB-1 dated facts, CB-2 the acceptance baseline and review, CB-3 owners), because those record what a running organisation cannot backfill; the original reading follows: CB-1/CB-2 (a rejected duplicate remembered; the coverage number and "fix this one")
    ship in days with no model call; foundations next; the thesis last. (b) **Who is asked whether a recommendation
    worked — the METRIC'S OWNER**, *not* as recommended (the recommendation was the accepting person, which needed no
    owner resolution). Consequence: idea 22 (CB-4) moves behind owners (CB-3); the accepting person is asked only while
    the owner is unresolved. (c) **The quarter's priorities live in organisation settings**, as recommended — people
    write them, they already win over inference. (d) **The first "said" source is filed Slack thread replies**, as
    recommended — they already arrive; uploaded documents (idea 7) follow. Nothing started; the register stays at zero
    OPEN — every clause is answered.

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
§3.10) · a hub that moves rows (what leaves is measured information, never data — §3.18) · a
model that decides who receives what, or which context outranks which (§3.18).

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
