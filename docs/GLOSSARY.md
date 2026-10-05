# Glossary — the platform's vocabulary

**One word per concept. One concept per word.** If you need a word that is not here, add it
here in the same PR that introduces it.

This is the authority for names in code, UI copy, LLM prompts, flag labels and docs. The
plan that produced it — with the file:line evidence and the phased burn-down — is
`VOCABULARY_UNIFICATION_2026-08-01.md` (absorbed into `ROADMAP.md`; recoverable from git history). The
"don't use" column is enforced by `tests/unit/test_vocabulary_ratchet.py`: a baseline may
fall, never rise.

---

## Answering

| Use this | For | Don't use |
|---|---|---|
| **Deep analysis** | The autonomous multi-phase path — *both* the mode you pick and the record it produces (plural: deep analyses) | ADA, Agentic, "investigation" *in anything a user reads* |
| **Quick answer** | The fast NL→SQL→answer path | "Insight" as a mode, chat, `direct` as a user word |
| **Survey** | A wide question answered by many cuts at once | "landscape", "wide wave"; `explore` in anything a user reads |
| **Knowledge answer** | A definitional answer from the knowledge base | `final_text` |
| **Overview** | The first-look tour of a newly connected schema | — (Home is Home; the catalog's per-table tab is "Summary") |
| **Exploration** | Background autonomous learning about the data | cartography |
| **Answer** | Any reply to any question | — |
| **Report** | The document a deep analysis or survey produces | `ada_report`, `ADAReport` |

**Deep analysis vs `investigation`.** "Deep analysis" is the only spelling users, prompts,
CLI output and flag labels may use. `investigation` survives as the **internal** spelling —
the `investigations` table, the `/investigate` route, the `investigation` job kind and the
ledger keys — because renaming a persisted identity orphans history. Backend identifiers
keep it; frontend identifiers and every user-visible string do not.

## Facts and artifacts

| Use this | For | Don't use |
|---|---|---|
| **Finding** | A discovered, evidence-backed fact shown to the user | **insight**, signal, pattern, fact, domain intelligence |
| **Narrative** | The prose enrichment attached to a quick answer | insight (the `_InsightResult` sense) |
| **takeaway** | The one-line summary of a single sub-question | insight (the per-subquestion sense) |
| **Issue** | A diagnostic raised by a guard or validator | guard classes named `*Finding` |
| **Statement** | A metric's SQL: a whole `SELECT` (CTEs allowed) that returns one row with the metric's value — every metric written since 2026-09-26 | "expression" or "formula" for a metric's SQL in anything a user reads |
| **Grain** | The date a metric's row counts on, written `schema.table.column` — the table because a statement is cut to a range by filtering that table | "time column" in anything a user reads |
| **Claim** | The atom of the Record (the 2027 study §G, phase 1 — `aughor/record/claims.py`): a dated statement about the business that carries its warrant, its owner, its tier on the authority ladder, its status (Final · Provisional · To date), both clocks (`as_of`, the data's date; `recorded_at`, the booking's) and, once counted, how often its class has been right. Kinds: observation · finding · reading · definition · hypothesis · prediction · said · cause. A statement a person verified — the word's earlier, narrower sense — is a claim at tier `approved` or with an attestation warrant | assertion; "fact" for the stored thing; a model's own confidence as a number |
| **Prediction** | A claim of kind prediction: a metric, a direction, an interval at a stated coverage, the method that produced it and the date it settles on; scored by code when its range is Final, never by a judge | forecast (as a stored thing — the gate's law 5 keeps the word for what never departs unscored), estimate |
| **Decision** | The organisation's choice, booked as a by-product of accepting a recommendation, approving an action or declaring it in a sentence (`aughor/record/decisions.py`): the question, the options, the one chosen, the claims relied on as recorded at that moment, dissent, and the expectation booked with it; the review date set at the moment of deciding | recommendation outcome (that is the older playbook record it supersedes), choice log |
| **Outcome** | What became of a decision, measured on its review date on settled days: the actual against the expectation AND against the metric's own baseline, with a verdict (as expected · better · worse · cannot tell) and what was written back | result, impact |
| **Inquiry** | The durable object a deep analysis runs inside (the 2027 study §G and §I, phase 2 — `aughor/record/inquiry.py`): the question, who opened it (a person · a monitor · a restated claim · a review), its runs with their verdicts, its hypotheses as claims with their state (open · supported · refuted · abandoned), what it established, what stays open and what would settle it, its state (open · waiting · closed) and the date it wakes without being asked. A refuted hypothesis on it is memory, read before the next run on the connection proposes its own | investigation (the frozen name of one run), case, thread, ticket |
| **Run verdict** | How a run ended, typed and booked for every run: answered · contradicted · no data · no definition · withheld · out of budget · tool failed — never an empty result, so a failure and a true negative never read alike | error, "no results", status alone |
| **Scenario** | A projection FOR a decision, an inquiry or a mission (the 2027 study §L, phase 3 — `aughor/record/scenario.py`): its assumptions, each with its source and whose it is; the predictions made under it, each carrying its **method** on the ladder (identity · declared · history, then intervention · simulation · learned) and taking the weakest method on its path as its tier; its limits in words. A scenario with no decision attached is a toy | simulation (as the stored thing), forecast (for the stored thing), what-if |
| **Method** | How a projection was produced, named from the scenario ladder, and what it must say: identity says what it held fixed; declared says whose assumption it is; history says its interval and its backtest error on this metric. A prediction's method is what calibration is counted by | model (for the method), algorithm |
| **Briefing** | The periodic narrative artifact, and its subscription | brief (as the artifact), digest, Intelligence Digest |
| **What we know** | The Briefing's standing view: everything the platform has learned, not tied to dates (Arc BR, ROADMAP §3.48) | Standing, "history" (both survive as internal names only) |
| **Range** | The days a Briefing covers: a preset — Day, Week, Month, Year, Month to date, Year to date — or a custom first and last day | window (in anything a reader sees) |
| **Final · Provisional · To date** | A figure's status: its days (and, for a cohort, its outcome) have settled; have not yet; the range is still under way | preliminary, estimate, partial |
| **Cockpit** | A standing set of cards a person keeps watching for one area — returns, pricing. It is theirs alone, and they keep as many as they like, in the Cockpit tab beside the Briefing; each is composed from a spec — tabs, sections and cards shown by a condition (Arc CT, ROADMAP §3.50). Until CT-7 the Briefing held one unnamed cockpit per connection, and a Data Canvas could hold one | dashboard, board (in anything a reader sees) |
| **Card** | One measured thing on a cockpit — a figure, a chart, a watch or a note — kept in the card store with its SQL, its limits and its history. A cockpit's spec holds a card's id and nothing about what it measures | tile, widget |
| **Section** | A titled group of cards inside a cockpit | group, block (in anything a reader sees) |
| **Within · Over · Unmeasured · Withheld** | A card's status as the host says it to a cockpit: inside its limit; past it; not measured, or with no limit to be past; not for this reader to see. A withheld card stays in its place and says so | breached, alerting; "hidden" for withheld (a card hidden by its condition is *waiting*) |
| **Run** | One execution of anything | session, episode (a step *inside* a run is a **step**) |
| **Trace** | The telemetry kept ABOUT one run — the `session_events` it wrote, reconstructed | run (a trace is the record, not the execution) |
| **Trajectory** | One run's trace with its steps' tool, arguments and results, its answer, and the reward attached to it — the one record the exporters read (Arc TJ, ROADMAP §3.47). A trace without a reward is not a trajectory | episode; rollout (a rollout is the act of producing one or more trajectories for one problem, not the record) |
| **Segment** | A saved, named filter over an entity's rows | ObjectSet |
| **Query template** | A reusable governed SQL template | OntologyAction |

## Acting

| Use this | For | Don't use |
|---|---|---|
| **Action** | A governed write to the data | kinetic |
| **Notification** | An outbound message (webhook, Slack, Jira) | Action Hub |
| **Approvals** | The queue of actions awaiting a human | the kinetic "inbox" (one **Inbox** exists: recommendations) |
| **Monitor** | A watch-a-metric rule | — |
| **Automation** | The condition→effect engine | — |
| **Only if** | A guard on ONE step: it runs only when the guard holds against what earlier steps published. `when` is the wire's field name | "When" (the automation's trigger already owns that word on the canvas), filter, condition (that is the trigger's) |
| **For each** | A fan-out on ONE step: it runs once per item of a list, and each iteration reads its item as `item.<field>` (a scalar as `item.value`). `for_each` is the wire's field name, and the surface word too — there is no collision to translate away | loop, iterate, batch (a batch is one send of many things; this is many sends) |
| **Otherwise** | The route on ONE step: it runs exactly when the named step's Only if was evaluated and did NOT hold — an undecided guard takes neither arm. `else_of` is the wire's field name | else/branch/if-else (programming words for a drawn surface), fallback (that is the every-step-failed escape hatch), condition |
| **From any** | The join: a binding that reads the first of several references that resolved (`{"$from_any": [...]}`), which is how one step runs after either arm of a route. Every alternative is validated, awaited and drawn | merge (git's word), first-of, coalesce (SQL's) |
| **In parallel** | An automation's step scheduling: steps run as their arrows allow — each waits for the steps it reads and nothing else. "In order" is the default and the pre-DS-7 sequential walk. `scheduling` is the wire's field name | concurrent/async/frontier (implementation words for a drawn surface), fan-out (that is For each — many sends of ONE step) |
| **Advice rule** | A "if metric X then recommend Y" entry | playbook (the `playbook/` sense) |
| **Starter** | A named question template that seeds a run | research playbook |

## Agents

| Use this | For | Don't use |
|---|---|---|
| **Explorer · Analyst · Responder · Watcher · Briefer · Curator** | The six built-in agents | Scout, "Insight" as an agent, charter (as a user word) |
| **SQL Engineer · Verifier · Narrator · Orchestrator** | The sub-roles inside a deep analysis | — |
| **Custom agent** | An agent a user created | persona, hired agent, user-defined agent, Gem |
| **Pack** | A domain bundle (entities, metrics, questions, evals) | specialist pack, expertise pack, Domain Expertise Pack, expert |
| **Agent Ops** | The workspace (layers: Overview · Roster · Attention · Activity · Runs) — renamed from "Agents" 2026-08-17 so the workspace and its Roster layer stop sharing a name | Agents (as the workspace name), Agentic Ops, Control Room, Fleet |
| **Map** | An agent's Roster tab: what it is scoped to, the doors it can be reached through, and the chains it operates — read-only, every node a field that already exists | Canvas (that is Data Canvas), Design (that is the automation editor's mode, and this edits nothing), Graph (that is the knowledge graph) |
| **Viewer · Editor · Owner** | The human permission ladder | "Analyst" as a *human* role — it names the agent |

The agent that runs deep analyses stays **Analyst**; the human RBAC role renamed to
**Editor** so the word means one thing. The stored grant value is still `"analyst"`.

## Platform internals

These are the package names on disk. Every rename below has landed; the old names do not
exist any more, so there is nothing to fall back to.

| Package | Holds | Renamed from |
|---|---|---|
| `aughor/actions/` | Governed writes to the data | `kinetic/` |
| `aughor/notifications/` | Outbound webhook / Slack / Jira delivery | `actions/` |
| `aughor/control_plane/` | Credential and inference vending | `platform/` (also shadowed stdlib `platform`) |
| `aughor/custom_agents/` | User-created agents | `user_agents/` (reads as the HTTP header) |
| `aughor/feedback/` | Human accept / correct / reject capture | `verify/` (one of four `verify`s) |
| `aughor/business_profile/` | Inferred industry and business model | `profile/` (collided with data profiling) |
| `aughor/lifecycle/` | Lifecycle / state-machine mining | `process/` |
| `aughor/pipeline/` | The generate→validate→execute→interpret template | `capability/` (collided with licence capabilities) |
| `aughor/demo/` | The bundled sample workspace | `samples/` (collided with row samples) |
| `aughor/files/` | Unstructured file store | `volumes/` |
| `aughor/briefing/` | Briefing subscriptions and delivery | `briefs/` |

Other internals: an **ambiguity probe** (`agent/ambiguity_probe.py`, was `soma`) generates
candidate readings and asks only when they diverge. Say **validate** for SQL checking
(`trust/`), **feedback** for human verdicts, **check** for claim verification — `verify`
named all three plus a quality gate.

**No import shims were left behind.** The plan originally called for them, but a shim would
keep the retired word alive in the tree — and the ratchet would rightly count it. Every
reference in the repo moved atomically instead. An out-of-repo script importing
`aughor.platform` will need updating; the table above is the map.

`verify` currently names four unrelated things (SQL validation in `trust/`, human feedback
in `verify/`, claim checking in `agent/verify.py`, a quality gate in `explorer/verify.py`).
Only the first keeps the word in prose: say **validate** for SQL, **feedback** for humans,
**check** for claims.

---

## External names

**Keep** the name of anything we actually integrate with — DuckDB, MotherDuck, MLflow,
Langfuse, Snowflake, BigQuery, the AG-UI protocol, every connector. Naming the product you
connect to is not jargon.

**Keep** attribution headers. `aughor/sql/readonly.py` and `aughor/sql/tables.py` are
Apache-2.0 adaptations of Superset code and say so; `NOTICE` records them. That is a licence
obligation.

**Don't** name our own features after products that inspired them. No "Genie-style",
"Foundry rule", "Palantir-grade", "Databricks-style" in identifiers, UI copy, prompts, flag
metadata, or CSS comments. Where a design genuinely came from a study, cite the document
once — `(see docs/GENIE_DOCS_TEARDOWN_2026-07-26.md)` — instead of describing the feature as
the brand.

**Study documents keep their names.** `docs/*_STUDY_*.md` are historical records.

**Fixture names** (BeautyCommerce, missimi, swiss_air) are fictional demo data — fine to
keep, but don't reach for them in a production docstring when a generic sentence works.

---

## Names that are frozen

These are persisted identities. They are never renamed; they are mapped to a display word at
the boundary. If you are tempted to rename one, you are about to orphan history.

- Ledger `natural_key` prefixes `ada:` and `insight:`; artifact kinds `ada_report`, `finding`
- The `investigations` table, the `/investigate` route, the `investigation` job kind
- **The four `STRUCTURAL_MODES`** — `direct`, `investigate`, `explore`, `final_text`.
  `query_mode` is a field on the checkpointed graph state and the checkpointer writes to
  `data/checkpoints.db`, so these values sit on disk in every paused run. Display words map
  at the boundary: Quick answer · Deep analysis · **Survey** · Knowledge answer.
  `aughor/agent/explore.py` keeps its name deliberately — renaming it to `survey.py` while
  the mode id stays `explore` would trade one mismatch for another
- The licence capability **value** `"analysis.deep"`
- Job kinds; agent ids (`scout`, `analyst`, `insight`, …); sub-role ids in `agent.handoff`
  payloads; the `agent_governance` store name and keys; session-log and checkpoint `agent_id`
- The RBAC role value `"analyst"`
- DB columns (`investigations.origin_insight_id`, `user_agents.*`), the Qdrant payload key
  `insight_id`, dashboard card `source="insight"`
- The pack on-disk format (`pack.yaml`, `expertise.md`, manifest keys)

**Flag names are renameable, but only through the alias layer** — `RENAMED` and
`RETIRED_ENV` in `aughor/kernel/flags.py`. Editing a `FLAG_ENV` key on its own strands the
operator's env var, their persisted override row, and any script that passes the old name.
