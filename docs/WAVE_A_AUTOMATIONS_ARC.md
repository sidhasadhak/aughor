# Wave A — Automations: PR arc

Scoped 2026-07-23 from [`docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md`](PALANTIR_FOUNDRY_STUDY_2026-07-22.md) §5,
grounded by a code-mapping pass over the three schedulers, the kinetic executor, and the kernel job
spine. Mirrors the [Wave K arc](WAVE_K_KINETIC_PLANE_ARC.md) format: each PR carries a flag (default
off), a test estimate, and a **pre-registered decision gate**.

**Wave A depends on Wave K** — "effects execute declared actions" is the joint, and K1–K5 merged in
[#201](https://github.com/sidhasadhak/aughor/pull/201).

---

## 0. What this is, and what it is NOT

Aughor already *reacts* — it just does so three separate times, in three modules that cannot see each
other. Wave A makes **condition → effect** one declared, governed, inspectable thing.

**IS:**
- **One engine**: a declared `Automation` binds combinable **conditions** (time · metric · source
  change · entity appearance) to ordered **effects** (investigate · brief · notify · execute a
  declared `KineticAction`), with muting, pausing, expiry, jittered retries, a fallback effect, and
  **per-run history**.
- **The write path stays governed**: an effect that writes goes through `execute_kinetic_action`
  ([`kinetic/executor.py:222`](../aughor/kinetic/executor.py)) — the same criteria → approval → audit
  pipeline a human gets. Wave A adds **no** second write path.
- **A staged-proposal queue with an agent decision log**, so an autonomous write is *proposed*,
  recorded with its reasoning, and applied only on human accept.
- **Change detection by cheap source version probes** (max transaction id / max activity timestamp /
  snapshot fingerprint) instead of "it has been N days."

**IS NOT:**
- **Not a new execution runtime.** Effects dispatch through primitives that already exist
  (`kernel().submit`, `deliver_subscription`, `fire_action`, `execute_kinetic_action`). The engine
  decides *whether* and *when*; it never learns *how*.
- **Not autonomous writes by default.** Nothing above LOW risk auto-fires — that property is
  inherited from K2, not re-implemented, and A must not weaken it.
- **Not a monitors/briefs rewrite.** A5 *adopts* them behind a flag with the legacy schedulers intact
  until the adoption is proven on real runs.

**Pre-registered guardrails:** every PR below states the one observation that would make it a
failure. If a gate can't be met, the PR is wrong, not the gate.

---

## 1. The finding that shaped the scope

The study says Wave A should "unify monitors + briefs + explorer re-arm under one engine." The code
says those three are not three configurations of one engine — they are **three engines that happen to
agree**, plus one that is not a trigger at all.

| Today | Reality | file:line |
|---|---|---|
| Monitor scheduling | Own `BackgroundScheduler`, own `_make_job_fn`, `misfire_grace_time=300` | [`monitors/scheduler.py:27`](../aughor/monitors/scheduler.py) |
| Brief scheduling | A **near-verbatim copy** of the above — own scheduler, own `_make_job_fn`, `misfire_grace_time=3600`. Its own docstring says "Mirrors aughor.monitors.scheduler" | [`briefs/scheduler.py:21`](../aughor/briefs/scheduler.py) |
| Conditions | **Six already exist** — `threshold_cross`, `trend_reversal`, `anomaly`, `segment_drift`, `data_freshness`, `any_change` — but as a `Literal` *inside* `Monitor`, reachable only by a monitor | [`monitors/models.py:49`](../aughor/monitors/models.py) |
| Brief conditions | **Time only.** `resolved_cron()` — a brief cannot fire on a metric at all | [`briefs/models.py:39`](../aughor/briefs/models.py) |
| Effects | Monitor → **exactly one**: append a `MonitorAlert`. Brief → **exactly one**: `deliver_subscription`. Neither can do the other's | [`monitors/scheduler.py:66`](../aughor/monitors/scheduler.py), [`briefs/scheduler.py:42`](../aughor/briefs/scheduler.py) |
| Muting / pausing | `grace_period_hours` — a *severity-aware anti-flap debounce*, monitor-only. There is no pause, no expiry, no mute-until | [`monitors/models.py:40`](../aughor/monitors/models.py) |
| Retries | **None.** A failed tick is logged and dropped; the next cron fire is the only retry | [`monitors/scheduler.py:84`](../aughor/monitors/scheduler.py) |
| Run history | Monitors persist only **fired alerts**. A tick that evaluated cleanly, or crashed, leaves **no row** — "did it run?" is unanswerable | [`monitors/store.py:285`](../aughor/monitors/store.py) |
| "Explorer re-arm" | **Not a trigger.** `explore_watermark.json` is a per-(conn,table) max-activity timestamp used to *narrow a scan* (`delta_clause`), consumed only inside an already-running exploration | [`explorer/watermark.py:42`](../aughor/explorer/watermark.py) |
| Staged proposals | `Proposal` is a **dataclass, never persisted** — proposals are live per-answer and die with the response (recorded as a K5 follow-on) | [`kinetic/propose.py:39`](../aughor/kinetic/propose.py) |
| `trigger_investigation` | **Still an open seam** — K2 raises `KineticDispatchError` for it. The docstring says "wired in K4"; K4 shipped the *proposer*, not this dispatch | [`kinetic/executor.py:199`](../aughor/kinetic/executor.py) |

**Three findings that change the plan:**

1. **The six condition kinds are not new work — they are trapped.** They already exist and are
   already tested, but as monitor-private enum values. A1's job is to *free* them, not invent them.
   Anything that reimplements `run_monitor`'s statistics is a regression, not a wave.
2. **"Explorer re-arm" does not exist to unify.** The watermark is a scan optimizer, not a trigger.
   The study's `source_change` condition is **net-new** — and the watermark is the right *shape* to
   generalize (cheap probe, per-connection, JSON-backed, fail-open to "run fully"), which is A3.
3. **Wave A closes a Wave K seam.** `trigger_investigation` has no dispatcher. Wave A's `investigate`
   effect is that dispatcher — so A2 makes an existing declared-action kind executable rather than
   adding a parallel one. This is the concrete form of "A depends on K."

**Naming.** Aughor now has *four* "action"-adjacent concepts (`OntologyAction` read-templates,
ActionHub `ActionTrigger` webhooks, Wave K `KineticAction`, and now Wave A `Effect`). An **Effect is
not a new action type** — it is a *reference to* one of the first three plus the arguments to invoke
it with. Docs and UI must never call an Effect an "action" unqualified.

---

## 2. The deterministic ⁄ model-gated split

| PR | Needs a model? | Why |
|---|---|---|
| **A1** Automation model + store + run history | **No** | pydantic models + a SQLite store |
| **A2** the one condition→effect engine | **No** | deterministic gate order; probes + dispatch injected in tests |
| **A3** source version probes (change detection) | **No** | `MAX(id)` / `MAX(ts)` / row-count fingerprint — plain SQL |
| **A4** staged-proposal queue + agent decision log | **Persistence: no.** Producing a proposal: yes (K4's proposer, already built) | the queue is a store; the model already exists upstream |
| **A5** adopt monitors + briefs onto the engine | **No** | a translation layer + equivalence tests |
| **A6** Automations surface (frontend) | No | UI over A1–A4 |

**A1–A3 and A5 need zero quota.** Only A4's *upstream* (the K4 proposer) calls a model, and that is
already shipped and flag-gated.

---

## PR-A1 — The Automation model + store + run history

**Scope.** `aughor/automations/models.py`: `Automation` (id, org/conn scope, name, `conditions:
list[Condition]`, `condition_logic: all|any`, `effects: list[Effect]`, `fallback_effect`, `enabled`,
`paused_until`, `expires_at`, `max_retries`, `retry_backoff_seconds`) · `Condition` (kind + typed
config) · `Effect` (kind + target ref + params) · `AutomationRun` (append-only: outcome, which
conditions fired, each effect's status, attempt count, duration, error). `aughor/automations/store.py`
clones the [`monitors/store.py`](../aughor/monitors/store.py) idiom — `resolve_db_path`, forward-only
migrations, `purge_connection` for the catalog-delete cascade.

The six condition kinds are **re-exported from the monitor vocabulary**, not redefined.

**Flag** `automations.engine` (default off) · **Tests** ~24 · **Decision gate:** an `Automation` with
two conditions and two effects round-trips model → SQLite → model byte-identically including every
lifecycle field; an `AutomationRun` records a tick that fired **nothing** (the case monitors cannot
represent today); deleting the connection purges both tables. If a clean no-op tick leaves no row,
the gate fails — "did it run?" is the question this store exists to answer.

---

## PR-A2 — One condition→effect engine

**Scope.** `aughor/automations/engine.py` — `run_automation(automation, *, probe=None, dispatch=None)`,
the **only** way an automation fires. Gate order is load-bearing and mirrors K2's discipline (cheap,
side-effect-free gates first; the only step that can cause a side effect is last):

```
enabled → not expired → not paused/muted → evaluate conditions (all|any)
        → effects in declared order → jittered retry on failure → fallback effect → record run
```

Effect dispatch is injectable (`Dispatch` seam, exactly as
[`kinetic/executor.py:159`](../aughor/kinetic/executor.py)). The default dispatcher wires
`investigate` → a supervised `kernel()` job draining `build_ask_stream` at `depth="deep"` (the real
answer path, via the same in-process technique the evals `ask_target` uses), `brief` →
`deliver_subscription`, `notify` → `fire_action`, and `kinetic_action` →
`execute_kinetic_action` — never a bypass, so criteria/approval/audit apply unchanged. An unwired
kind raises rather than no-ops.

> ⚠️ **Scope note, stated precisely.** This gives *automations* a working investigation dispatcher.
> It does **not** by itself close K2's `trigger_investigation` branch
> ([`kinetic/executor.py:199`](../aughor/kinetic/executor.py)), which still raises: wiring that
> would make `kinetic` depend on `automations`, inverting the wave dependency. Closing it properly
> means lifting the runner into a module neither package owns — a follow-on, not a claim A2 gets to
> make.

**Flag** `automations.engine` · **Tests** ~34 · **Decision gate:** a paused, expired, or
condition-negative automation performs **zero** effect dispatches and still writes a run row saying
so; a `kinetic_action` effect whose submission criterion fails returns the **authored message
verbatim** and dispatches nothing; a HIGH-risk effect without approval records `approval_required`
and fires nothing. If any effect fires on a gated tick, or the engine reaches the warehouse when
muted, the gate fails.

> ✅ **Gate met (2026-07-23), proven on the live path** — the real app, the real overrides YAML, the
> real Wave-K executor, against the `workspace` connection:
>
> | tick | outcome | effect |
> |---|---|---|
> | `amount_eur=25000` | `fired` (10ms) | `criterion_failed` — *"Refunds over EUR 10,000 need finance sign-off."*, byte-identical to the authored YAML, 1 attempt |
> | `amount_eur=500` | `fired` (6ms) | `approval_required` — risk `high`, nothing executed |
> | muted | `gated` (0ms) | none; zero conditions evaluated |
>
> **The live run found two defects the green tests could not**, both now fixed and regression-tested:
> 1. **`dispatch_error` was retriable.** Naming an action the connection does not declare burned
>    **48 seconds** of a held scheduler thread retrying an id that could never resolve. A structural
>    error is a *verdict*, not a fault — only `failed` retries in-tick now.
> 2. **A missing schema ontology reported "not a declared action".** A schema that was never built
>    fell back to another schema's graph and blamed the *declaration*, pointing the diagnosis at the
>    wrong thing entirely. The three cases are now distinguished in the message.

---

## PR-A3 — Source version probes (change detection)

**Scope.** `aughor/automations/probes.py` — a cheap per-(connection, table) **source version**:
`MAX(<pk>)` / `MAX(<ts>)` / `(row_count, MAX(ts))` fingerprint, chosen by what the table has, one
bounded query. Persisted like the watermark, but as a *trigger* input rather than a scan narrower;
the `source_change` condition fires when the version advanced since the last recorded run. Generalizes
[`explorer/watermark.py`](../aughor/explorer/watermark.py) without changing its scan behaviour.

**Flag** `automations.source_probes` (default off) · **Tests** ~20 · **Decision gate:** inserting a
row advances the probe and fires the condition exactly **once** (a second tick with no new rows does
not re-fire); a table with no usable id/timestamp column fails **open** to "changed" with the reason
recorded, never silently never-fires. If a probe costs a full scan on a large table, the gate fails.

---

## PR-A4 — Staged-proposal queue + agent decision log

**Scope.** Persist K4's `Proposal` (today a live-only dataclass) as a queue: proposal + model
reasoning + validation status + proposer identity → human accept/reject → on accept, run through
`execute_kinetic_action` and receipt it. The decision log records **both** outcomes with the actor,
so a rejected proposal is evidence, not a gap. Precedence follows the ambiguity ledger's
`_SOURCE_RANK` discipline ([`semantic/ambiguity_ledger.py:47`](../aughor/semantic/ambiguity_ledger.py)) —
machinery never clobbers a human decision.

**Flag** `automations.proposals` (default off) · **Tests** ~22 · **Decision gate:** a proposal
survives a process restart, accept executes it **exactly once** (double-accept is a no-op, not a
second dispatch), and reject leaves an auditable row with no side effect. If accept can fire twice,
the gate fails.

---

## PR-A5 — Adopt monitors + briefs onto the engine

**Scope.** A translation layer: every `Monitor` and `BriefSubscription` reads as an `Automation`
(cron condition + its single effect), executed by the A2 engine, with the legacy schedulers still
present and authoritative until the flag flips. Equivalence tests assert the engine produces the
**same alert/delivery** as the legacy path for the same input.

**Flag** `automations.adopt_legacy` (default off) · **Tests** ~26 · **Decision gate:** for a corpus
of existing monitors and subscriptions, engine output equals legacy output — same alert severity,
message, and debounce behaviour — and flipping the flag off restores the legacy path with no data
migration. If the anti-flap debounce changes behaviour, the gate fails.

---

## PR-A6 — Automations surface

**Scope.** Author conditions/effects, see per-run history with the reason a tick did nothing, mute /
pause / expire, and work the proposal queue. Frontend-heavy; pairs with Wave S.

**Flag** reuses `automations.*` · **Tests** ~10 · **Decision gate:** author → tick → history →
proposal accept renders end-to-end against the local fixture with no console errors.

---

## Sequencing & dependencies

```
A1 (model/store) ──▶ A2 (engine) ──▶ A3 (source probes) ──▶ A5 (adopt legacy) ──▶ A6 (surface)
                          └────────▶ A4 (proposal queue) ─────────┘
                          (A2 'kinetic_action' dispatch is Wave K's executor, unchanged)
```

A1+A2 ship together: A1 alone is a schema with no consumer, which is exactly the
BUILT-but-not-LEVERAGED failure mode the platform review flagged.
