# Glossary — the platform's vocabulary

**One word per concept. One concept per word.** If you need a word that is not here, add it
here in the same PR that introduces it.

This is the authority for names in code, UI copy, LLM prompts, flag labels and docs. The
plan that produced it — with the file:line evidence and the phased burn-down — is
[`VOCABULARY_UNIFICATION_2026-08-01.md`](VOCABULARY_UNIFICATION_2026-08-01.md). The
"don't use" column is enforced by `tests/unit/test_vocabulary_ratchet.py`: a baseline may
fall, never rise.

---

## Answering

| Use this | For | Don't use |
|---|---|---|
| **Deep analysis** | The autonomous multi-phase path — *both* the mode you pick and the record it produces (plural: deep analyses) | ADA, Agentic, "investigation" *in anything a user reads* |
| **Quick answer** | The fast NL→SQL→answer path | "Insight" as a mode, chat, `direct` as a user word |
| **Survey** | A wide question answered by many cuts at once | `explore` as a question mode, landscape, wide wave |
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
| **Claim** | A statement a human has verified | — |
| **Briefing** | The periodic narrative artifact, and its subscription | brief (as the artifact), digest, Intelligence Digest |
| **Run** | One execution of anything | session, episode (a step *inside* a run is a **step**) |
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
| **Advice rule** | A "if metric X then recommend Y" entry | playbook (the `playbook/` sense) |
| **Starter** | A named question template that seeds a run | research playbook |

## Agents

| Use this | For | Don't use |
|---|---|---|
| **Explorer · Analyst · Responder · Watcher · Briefer · Curator** | The six built-in agents | Scout, "Insight" as an agent, charter (as a user word) |
| **SQL Engineer · Verifier · Narrator · Orchestrator** | The sub-roles inside a deep analysis | — |
| **Custom agent** | An agent a user created | persona, hired agent, user-defined agent, Gem |
| **Pack** | A domain bundle (entities, metrics, questions, evals) | specialist pack, expertise pack, Domain Expertise Pack, expert |
| **Agents** | The workspace (layers: Overview · Roster · Attention · Activity · Runs) | Agentic Ops, Control Room, Fleet |
| **Viewer · Editor · Owner** | The human permission ladder | "Analyst" as a *human* role — it names the agent |

The agent that runs deep analyses stays **Analyst**; the human RBAC role renamed to
**Editor** so the word means one thing. The stored grant value is still `"analyst"`.

## Platform internals

| Use this | For | Don't use |
|---|---|---|
| **ambiguity probe** | Generating candidate readings and asking only when they diverge | soma |
| **stall detector** | Detecting a run that has stopped making progress | wandering |
| **feedback** | Human accept/correct/reject capture | verify (that sense) |
| **control plane** | Credential and inference vending | platform (it also shadows stdlib `platform`) |
| **business profile** | Inferred industry and business model | profile (that sense — data profiling is the other one) |
| **demo data** | The bundled sample workspace | samples (that sense — a row sample is the other one) |
| **AI functions** | LLM operators callable from SQL | semops |

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
