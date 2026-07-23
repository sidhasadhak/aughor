# Wave K — Kinetic plane: PR arc

Scoped 2026-07-23 from [`docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md`](PALANTIR_FOUNDRY_STUDY_2026-07-22.md) §5,
grounded by three code-mapping passes over the actions/ontology, ambiguity-ledger, and
tool-surface/governance foundations. Mirrors the [Wave E arc](WAVE_E_SESSIONS_EVALS_ARC.md) format:
each PR carries a flag (default off), a test estimate, and a **pre-registered decision gate**.

---

## 0. What this is, and what it is NOT

Palantir sells the **loop** (data → semantics → decision → write-back → data). Aughor already has the
read half with a deterministic guard plane Foundry lacks. Wave K adds the **governed kinetic half** —
without surrendering the property that makes the read half trustworthy.

**IS:**
- A **declared-action substrate**: named, typed-parameter actions defined in the per-connection ontology
  YAML, each with **submission criteria whose authored failure messages are shown verbatim** to humans
  AND the LLM, dispatched through **one** governed executor.
- An **edits-as-overlay ledger**: human annotations/corrections ("this outlier is a known event")
  that **merge at read time** with explicit precedence and **survive refreshes** — never mutating source.
- A narrowing of the agent's write surface to: **scoped read query + declared trusted queries +
  declared actions** — never freeform.

**IS NOT:**
- **Not source-data writes.** The read-only gate ([`security/safety.py:86`](../aughor/security/safety.py),
  [`sql/readonly.py`](../aughor/sql/readonly.py), enforced fail-closed at
  [`db/connection.py:78`](../aughor/db/connection.py)) STAYS. A "kinetic action" is an *annotation*, a
  *side-effect* (notify/webhook/trigger), or a *governed read-template* — not an INSERT/UPDATE/DELETE.
  This is the safety property, kept.
- **Not a new agent tool-calling runtime.** There is no LLM tool-registry today (the agent is a fixed
  pipeline); Wave K adds a *declared* action surface the planner emits into, not native function-calling.
- **Not Foundry's Spark/CBAC machinery.** Lean patterns over substrates we already have.

**Pre-registered guardrails (post-hoc rationalisation is easy):** every PR below states the one
observation that would make it a failure. If a gate can't be met, the PR is wrong, not the gate.

---

## 1. The finding that reshaped the scope

The study says Wave K "builds on `ontology/actions.py`, ActionHub, approvals, RBAC." The code says those
foundations are **real but read-only / notify-only / default-off** — the declared **write-back** substrate
is net-new. Precisely:

| Foundation | Reality today | file:line |
|---|---|---|
| `OntologyAction` | Read-side SQL-template shortcut (`ACTION:id()`→subquery). Has **typed params** (`ActionParameter`) but **no** side-effect / submission / mutation concept; all 5 `action_type`s are read-side | [`ontology/models.py:215`](../aughor/ontology/models.py), [`ontology/actions.py`](../aughor/ontology/actions.py) |
| "ActionHub" | **Exists** — outbound webhook/slack/jira notify, SSRF-guarded, append-only logged, `Capability.ACTION_HUB`-gated. A *side-effect* surface, not DB write | [`actions/executor.py:82`](../aughor/actions/executor.py) `fire_action`, [`routers/actions.py`](../aughor/routers/actions.py) |
| `govern/actions.py` | **Exists** — graduated-approval dial (`classify`/`guard`/`audit`, risk enum, 428 flow). But only **3** `guard()` call sites, **9 of 12** `_RISK` actions unenforced, and **off unless `AUGHOR_ACTION_APPROVAL`** | [`govern/actions.py:128`](../aughor/govern/actions.py) |
| Approvals API | **Exists** — `/approvals/allow\|revoke\|allowlist\|audit`, 428→allow→retry | [`routers/approvals.py:23`](../aughor/routers/approvals.py) |
| RBAC | **Exists** — `Permission` enum + `policy.py` route→perm table, but inert unless identity on AND `Capability.RBAC_SSO`; AND-ed with licensing capability | [`rbac/policy.py:33`](../aughor/rbac/policy.py), [`rbac/deps.py:75`](../aughor/rbac/deps.py) |
| Ontology YAML `actions:` block | **Does not exist.** Graph is JSON-cached; the only per-connection ontology YAML is the **overrides file-tree** (`data/ontology_overrides/{conn}/{schema}/{kind}/{id}.yaml`), parsed at [`overrides.py:151`](../aughor/ontology/overrides.py); its `TargetKind` has no "action" kind | — |
| Ambiguity ledger (overlay template) | **Exists** — SQLite, per `(org_id,connection_id)`, `verify/verdicts.py` store idiom, **source-authority precedence** `_SOURCE_RANK={probe:1,user:2,verdict:3}` so machinery never clobbers a human. The exact shape to generalize | [`semantic/ambiguity_ledger.py:47`](../aughor/semantic/ambiguity_ledger.py) |
| Side-effect primitives | **All exist** — `fire_action` (notify), `kernel().submit("investigation"\|"exploration")` (trigger), `deliver_subscription` (brief) | [`kernel/jobs.py:145`](../aughor/kernel/jobs.py) |

**Naming collision to resolve up front:** three "action" concepts (`OntologyAction` read-templates,
`ActionTrigger`/ActionHub webhooks, Wave K declared actions). Wave K introduces **`KineticAction`** as the
declared unit that *composes* the other two; the docs/UI must never call all three "actions" unqualified.

**Net:** the substrate (schema, executor, overlay ledger) is net-new but sits on mature, reusable rails.
It is **~80% deterministic and hermetically testable** — only the agent *choosing* an action needs a model.

---

## 2. The deterministic ⁄ model-gated split (the headline for "ready for quota")

| PR | Needs a model? | Why |
|---|---|---|
| **K1** declared-action schema + YAML parse + registry | **No** | pure data model + YAML round-trip |
| **K2** one governed executor (validate → criteria → approval → RBAC → dispatch → audit) | **No** | deterministic dispatch; side-effects stubbed/faked in tests |
| **K3** edits-as-overlay ledger + read-time merge | **No** | SQLite store + a merge hook, clone of the ambiguity ledger |
| **K4** agent proposes a declared action end-to-end | **YES** | the planner must *choose* an action + params on real data |
| **K5** author/approve/annotate surface (frontend) | No (models optional) | UI over K1–K3; pairs with Wave S |

**K1–K3 can start today with zero quota.** K4 is the piece the $11/1,000-req-day OpenRouter unlock (2026-07-23)
was the precondition for — it is now provable. Build K1→K2→K3 while quota is irrelevant; K4 the moment the
substrate lands.

---

## PR-K1 — The declared-action schema + the `actions:` YAML seam

**Scope.** Introduce `KineticAction` (distinct from `OntologyAction`): `name`, `display_name`,
`params: list[ActionParameter]` (reuse the existing type), `kind: Literal["annotate","side_effect","query"]`,
`rule` (SQL template for `query`, or a side-effect spec), `submission_criteria: list[Criterion]` (each a
deterministic predicate over params + an **authored failure message string**), `side_effects:
list[SideEffect]` (`notify`/`webhook`/`trigger_investigation`), `risk: ActionRisk`, `origin`. Parse a
top-level `actions:` block by extending the overrides seam: add `"action"` to `TargetKind`
([`overrides.py:50`](../aughor/ontology/overrides.py)), `_EDITABLE`, a `_apply_action` dispatch branch, and
carry it onto the graph via `store.overlay_human_overrides()`. Surface via `routers/ontology.py`
(read-only list, mirroring `get_ontology_actions`).

**Flag** `kinetic.actions` (default off) · **Tests** ~22 · **Decision gate:** a hand-authored
`actions:` YAML block round-trips YAML → `KineticAction` → `OntologyGraph` → `/ontology/.../actions`, with
a malformed criterion rejected at parse (not at execute) and the authored failure message preserved
byte-for-byte. If the message is ever paraphrased or lost, the gate fails.

---

## PR-K2 — One governed executor path

**Scope.** A single `execute_kinetic_action(action_id, params, *, actor, scope)` that is the **only** way an
action runs: (1) validate/coerce params against `ActionParameter` types; (2) evaluate `submission_criteria`
deterministically — on failure return the **authored message verbatim** to caller AND (for K4) to the LLM,
no execution; (3) `govern.guard(action_id, scope)` — reuse the graduated dial, register each action in
`_RISK`; (4) RBAC `require_permission` via the `policy.py` table; (5) dispatch: `query`→existing
`expand_actions` template path, `side_effect`→`fire_action` / `kernel().submit`, `annotate`→K3 overlay
write; (6) audit every outcome (`action.kinetic` events). Wire the 9 currently-unenforced `_RISK` actions
while here.

**Flag** `kinetic.actions` + honours `AUGHOR_ACTION_APPROVAL` · **Tests** ~30 (side-effects faked;
`fire_action`/`submit` injected) · **Decision gate:** a HIGH-risk action with no approval returns **428 +
the authored failure/approval message**, writes an `audit=blocked` row, and performs **zero** side effects;
after `POST /approvals/allow` the identical call executes exactly once and audits `approved`. A criterion
failure must short-circuit **before** `guard()` (never approve then reject). If any side effect fires on a
blocked or criterion-failed action, the gate fails.

---

## PR-K3 — The edits-as-overlay ledger

**Scope.** New SQLite store `data/overlay_ledger.db` (env `AUGHOR_OVERLAY_LEDGER_DB`), org+connection-scoped,
cloning the [`verify/verdicts.py`](../aughor/verify/verdicts.py) idiom the ambiguity ledger already uses.
Record: `{org_id, connection_id, schema_scope, target (table / table.column / table.column + row-key),
kind (annotation|correction), body, source, precedence_rank, created_at, last_used_at}`. Precedence via a
`_SOURCE_RANK` copy (human > machine), override-wins merge modelled on
[`orgsettings/store.py:42`](../aughor/orgsettings/store.py). **Read-time merge:** extend
[`_attach_caveats` (`sql/executor.py:250`)](../aughor/sql/executor.py) with a **per-cell channel** (address
by row-index + column, since `rows` is `list[list]`) and add a column/metric-grain hook in
[`profile/store.py`](../aughor/profile/store.py) (which already transforms at read). Register a
catalog-delete purge hook (mirror `ambiguity_ledger.purge_connections` in `agent/bootstrap.py`).

**Flag** `kinetic.overlay` (default off) · **Tests** ~26 · **Decision gate:** an annotation written to
`(conn, table.col, row-key)` appears merged into that cell's `QueryResult` **after a connector rebuild**
(survives refresh), a machine-source annotation never overrides a human one on the same target, and
deleting the connection purges its overlay rows. If a refresh drops the annotation, or machine clobbers
human, the gate fails.

---

## PR-K4 — The agent proposes a declared action (⚠️ needs a model)

**Scope.** Give the planner the declared actions in-prompt (a `build_kinetic_actions_section`, sibling of
`build_actions_prompt_section`), let it emit a proposal `KINETIC:action_id(param=…)` with typed args, routed
through K2 as a **staged proposal** (agent proposes + reasoning → human accepts → executed + receipted),
never auto-fired above LOW risk. The agent's write surface is now exactly {scoped read SQL, `ACTION:` read
templates, `KINETIC:` declared actions}.

**Flag** `kinetic.agent_actions` (default off) · **Tests** ~15 hermetic (faked provider) + **1 live proof** ·
**Decision gate (live, needs quota):** on a real investigation over the demo connection, the agent proposes
a declared action with **valid typed params**, a criterion failure returns the authored message *to the
model* and it revises or abstains (no invalid execution), and a human-accept applies it + writes a receipt.
Run N≥3 (temp 0.1, no seed → report a band, never "deterministic"). If the agent emits freeform SQL writes,
or fabricates params a criterion should reject, the gate fails. **This is the piece the OpenRouter 1,000-req/day
unlock makes runnable.**

---

## PR-K5 — Author / approve / annotate surface (optional; folds into Wave S)

**Scope.** UI to author `KineticAction`s, view the staged-proposal queue, approve/reject (drives
`/approvals`), and add an annotation from any result cell (drives K3). Frontend-heavy — pairs with Wave S
momentum; not required to prove the loop.

**Flag** reuses `kinetic.*` · **Tests** ~10 · **Decision gate:** author → propose (agent) → approve →
receipt renders end-to-end against the local fixture with no console errors.

---

## Sequencing & dependencies

```
K1 (schema/YAML) ──▶ K2 (executor) ──▶ K4 (agent) ──▶ K5 (surface)
       └──────────▶ K3 (overlay) ──────┘   (K2 'annotate' dispatch calls K3)
```

- **K1 → K2** hard: the executor needs the model. **K2 → K4** hard: the agent proposes *into* the executor.
- **K3 ∥ K1/K2**: the overlay ledger is independent substrate; K2's `annotate` dispatch consumes it, so land
  K3 before K2's annotate branch (or stub it).
- **K1–K3 are the no-quota critical path** — do them first, in any order that respects K3-before-annotate.
- Cross-wave: Wave A (Automations) depends on K ("effects execute declared actions"); Wave G (Governance)
  hardens the same approval/RBAC seam K2 turns on. Wave K + Wave E together are the "guarded read path +
  governed write path" claim — no one else has both.

---

## Risks & honesty

- **Read-only regression is the cardinal risk.** K2's `annotate`/`side_effect` dispatch must NEVER route to
  connection `execute()` with DML. Add a test asserting no kinetic path reaches a mutating statement, and
  keep the [`sql/readonly.py`](../aughor/sql/readonly.py) gate in front of the `query` kind too.
- **The one existing raw-DDL escape** — [`program_planner.py:169`](../aughor/agent/program_planner.py)
  (`CREATE OR REPLACE TEMP VIEW … WHERE 1=0` via a raw handle, data-free, in-memory) — is the sole path that
  skips the gate today. Wave K must not widen it; note it so a reviewer knows it's pre-existing.
- **Governance is default-off.** Turning `AUGHOR_ACTION_APPROVAL` on changes behaviour for the 3 already-wired
  `guard()` sites (connection.delete, ontology.override×2). Graduate deliberately, with the `capability`
  flag-graduation discipline.
- **Determinism ceiling on K4** (same as Wave E): no seed, temp 0.1, Anthropic drops temperature, silent
  fallback swaps model mid-run — so K4's gate is **replication + causal attribution, never deterministic
  replay**. Every number is a band.
- **Submission-criteria fidelity is the product.** The authored failure message is shown verbatim to a human
  AND the model — a paraphrase (by us or by an LLM digest) defeats the whole point. Keep it a passed-through
  string end-to-end; never route it through a model. (Same lesson as the deterministic evidence condensation.)
- **Scope creep into Wave A.** Conditions/triggers ("when metric crosses X, execute action") are Wave A. K
  ships the *executor + declared unit*; A ships the *condition engine* that calls it. Resist merging them.

---

## Where this leaves Wave K

Substrate (K1–K3) is a ~78-test, zero-quota, hermetic build on mature rails; the kinetic loop is proven
(K4) with one live run now that OpenRouter carries 1,000 req/day. The defensible claim after K+E:
**the only platform whose agents are deterministically guarded on the read path and governed-by-declaration
on the write path — without ever surrendering read-only safety on source data.**
