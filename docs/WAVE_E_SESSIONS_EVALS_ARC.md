# Wave E — Sessions + Evals: PR arc

Scoped 2026-07-22 from [PALANTIR_FOUNDRY_STUDY_2026-07-22.md](PALANTIR_FOUNDRY_STUDY_2026-07-22.md) §5.
Five parallel code-mapping passes over the repo grounded every claim below in real signatures.

---

## 0. What this is, and what it is not

**Not** a rebuild of the Spider 2.0 harness. That was a benchmark-side shim measuring a shim; it was
deleted for good reason and must stay deleted (`nl2sql-scientific-benchmarking`,
`build-real-feature-not-bench-hack`).

What the Spider work actually produced was a **measurement discipline**, currently recorded only in
memory files and deleted branches:

- single runs flip-flop even at temperature 0 → **N≥3 replication, stable-win vs flaky**
- aggregate deltas lie at small n → **per-case causal attribution** (did the change *touch* this case?)
- a bare `except` made a broken feature look merely unhelpful → **prove it actually ran**
- and "it ran" ≠ "the model acted on it" → **prove the output changed in the intended way**
- post-hoc rationalisation is easy → **pre-registered decision gates**

Wave E makes that discipline a product feature that runs over Aughor's own paths, on the customer's
own data. That is the thing a bench harness can never be.

**Honest ceiling, stated up front:** we cannot make LLM output deterministic. There is no seed in any
backend path, no response cache, and the Anthropic backend drops `temperature` entirely
(`llm/provider.py:517-521`). The goal is therefore **replication + causal attribution**, never
"deterministic replay". Any PR in this arc that claims reproducibility is overclaiming.

### The finding that reshaped the scope

We do not have zero evals. We have **five mutually-unaware ones**, sharing no store, no record schema,
no scorer, and no capability gate:

| # | Surface | Scoring | State |
|---|---|---|---|
| 1 | `POST /eval/run` (`routers/system.py:16`) | `live=False` hardcoded — replays reference SQL and scores it **against itself** | ungated; CWD-relative path into unpackaged `evals/` ⇒ permanent 503 in a wheel; **zero callers** |
| 2 | `/semantic/{conn}/benchmarks` (`agent/benchmarks.py`) | string `must_contain` matching; runner **blanks all 8 prompt-context sections** so it measures a context-free model | full CRUD + shipped UI; **zero records ever authored**; DELETE ungated while POST/PUT are gated |
| 3 | `/agents/custom/{id}/goldens` + `/evaluate` (`user_agents/quality.py`) | **executes both sides, compares result sets** — order-insensitive, float-normalised 6dp, column-superset tolerant | injectable deps, capped at 20, runs the real path, MLflow span, tested, full UI — behind off-by-default `agents.user_defined` |
| 4 | `golden_sql_expanded.jsonl` (53) + `evals/sql_accuracy.py::score_single` | multi-reference execution accuracy, best-of wins | **load-bearing** — hermetic CI gate ×53; ratchet history says real accuracy ≈ **65%** (5 runs, 0.624–0.655) |
| 5 | `POST /packs/{id}/evaluate` (`packs/evalgate.py`) | declarative `expect` dict | **best concept**: evals as a *promotion gate*, `ActivationDecision{can_activate, pass_rate, reasons}` separating "passes" from "deployable" |

Two gifts fall out of that table:

- **Zero LLM judges exist anywhere in `aughor/`.** Every scorer is deterministic. That is exactly the
  foundation Foundry's evaluator library needs, and it matches our guards thesis rather than fighting it.
- **`eval.suite` is declared, sold as Enterprise (`licensing/capabilities.py:49`), and gates nothing** —
  zero `gate(Capability.EVAL_SUITE)` call sites. A free, pre-sold slot.

So Wave E is **consolidation**, not addition. Six PRs; none adds a sixth eval surface.

---

## PR-E1 — Session log: make the main path observable

**Why first.** The gap is worse than "no event schema". `telemetry.new_trace` is called *exactly once*
in the codebase (`routers/investigations.py:2474`, inside the deep path), so **quick `/ask` and `/chat`
never mint a trace id at all**. Their SQL goes through `db.execute` directly
(`investigations.py:1862`, `:1890`), bypassing `execute_guarded`, so it produces no spans; the audit
row that does record it (`security/audit.py`) has no correlation column. **A quick answer cannot be
reconstructed after the fact** — and quick is the most-used door. Separately,
`telemetry.log_generation` — the function that would record each LLM call — has **zero call sites**, so
model, latency, retries and the silent Anthropic fallback all vanish into aggregate counters.

**Scope**

1. **Fifth sink on the existing fan-out.** `telemetry.span()` (`:497`) and `mlflow_tool_span()` (`:272`)
   are already a 4-sink `ExitStack` fan-out with contextvar-threaded trace/span stack. Add
   `_session_log_span` beside `_task_history_span` (`:355-404`), entered outermost. This captures **all
   17 existing span sites with zero call-site edits**, inheriting the parent/child tree. Emit
   `tool_call` on enter and `tool_call_result` on exit with an explicit `success` boolean (today it is
   only inferable from `error_message IS NULL`), `duration_ms`, and `error_class`.
2. **Mint the trace at the one door.** `build_ask_stream` (`investigations.py:3635`) is the single
   composed generator shared by `POST /ask` and `POST /agui/run:316`, and its docstring already
   guarantees `request` is never dereferenced. Add one wrapper in that chain that mints the run id
   **up front** and pins `telemetry._active_trace_id` — every downstream span then inherits it,
   **including the quick path's, with no change to `_stream_chat`**. Same wrapper emits `user_request`
   before yielding and `final_response` / `execution_error` at exhaustion.
3. **Non-`/ask` doors** via `JobKernel._run` (`kernel/jobs.py:277`), which already scopes job/org/
   metering contextvars per run — covers explorer, briefs, monitors, birth.
4. **Per-LLM-call record.** Wire the dead `telemetry.log_generation` at the three points where
   `metering.record_llm` already fires (`provider.py:539`, `:588`, `:650`): model, role, prompt/
   completion tokens, latency, success, **retry count and whether the Anthropic fallback swapped the
   model mid-run** (`provider.py:446-462`, currently a WARNING log only).
5. **Storage** — `Migration(5, …)` in `kernel/ledger.py` beside `_create_task_history` (`:121`), with
   `session_event_insert` / `session_events` mirroring `:521-578`. Then add `"session_events"` to
   `AughorOpsConnection._OPS_TABLES` (`db/connection.py:899`) so it is **instantly NL2SQL-queryable** —
   the same one-line move `task_history` already proved.
6. **Retention from day one.** Neither `events` nor `task_history` has any prune/TTL/VACUUM today and
   both grow unbounded. A session log multiplies row volume; ship the policy with the table.

**Free wins unlocked by a join key** (each is a small, separate commit):
- `trust/receipt.py:144,148` — `executed_sql[].duration_ms` / `.row_count` are hardcoded `None`
  *because* receipts are built from lineage, not spans. Join to `sql.execute` spans and they become real.
- `security/audit.py` — add `trace_id` at the single writer (`db/connection.py:189`) and **every** SQL
  execution on **every** path becomes correlated.
- `Ledger.emit` (`:467`) — add a `trace_id` column defaulted from the contextvar; all 29 event kinds
  become trace-correlated with zero call-site edits.

**Flag** `obs.session_log` (default off) · **Tests** ~18 · **Decision gate:** ship only if a quick
`/ask` turn is fully reconstructible from `session_events` alone (request → tool calls → LLM calls →
final response) and p95 write overhead is under 5 ms/span. If the sink measurably slows the answer
path, make it async-buffered before shipping, not after.

---

## PR-E2 — Evaluator library: one protocol over the guard battery

**Why.** Guards are our differentiator and they are already standalone-callable — proven by precedent,
not theory: the deleted `evals/guard_coverage.py` (recover with `git show cad2d49:evals/guard_coverage.py`)
fired them over 135 predictions with zero agent, zero LLM, zero FastAPI, constructing a bare
`SQLiteConnection` per case. Connections are duck-typed throughout — there is no
`isinstance(conn, DatabaseConnection)` anywhere in the guards.

But there is **no common interface**: six mutually-incompatible return shapes (`list[Finding]` /
`str|None` / `Finding|None` / `bool` / `(sql, receipt)` / `(ok, reason)`). `routers/query.py:637-751`
hand-projects six of them into six differently-shaped JSON lists — the exact non-uniformity this PR fixes.

**Scope**

- New **`aughor/evals/`** package (product code; distinct from the repo-root bench `evals/` — keep the
  import paths visibly different and say so in the module docstring).
- `Evaluator` Protocol with `name` / `severity` / `requires` / `deterministic`, plus `EvalCase`,
  `EvalObservation`, `EvalScore` — modelled on `capability/pipeline.py`, and reusing
  **`trust.Check` verbatim** as the normalised finding so `Verdict.ok/blockers/warnings` semantics and
  receipt vocabulary stay singular.
- `requires` drives **skip, not fail**, when a case lacks a connection or column types — the fail-open
  contract every guard already honours.
- **Six thin adapters**, one per return shape, registering **~25 deterministic evaluators from existing
  code with zero guard rewrites**: readonly + disallowed-functions (BLOCK), E1 semantics, the 14 pure
  `fanout.*` detectors, composite-key, lint, capability-contract, join/filter value-domain, join
  coverage, grain fan-out, result-grain intent, insight soundness.
- Registry copying `capability/registry.py` verbatim (dict + register/get/`clear()`), and **add
  `"evaluators"` to `kernel/registries/manifest()`** — the established "what's plugged in" surface.
- Extract the `ProbeFn` bridge, currently hand-rolled in three places (`trust/__init__.py:122`,
  `routers/query.py:698`, and the deleted coverage script).
- Add `Verdict.to_dict()` — genuinely net-new; three call sites hand-project it today.

**Three traps the mapping surfaced** — each needs a test:
- `safety.preflight_repair` may call `SqlWriter.fix`, which **hits the LLM**. Exclude it from the
  deterministic set or gate it explicitly; a "deterministic" evaluator that silently makes a model call
  would poison every measurement in this arc.
- `trust_checks._COLTYPE_CACHE` (`:168`) is a module-global keyed by connection id. A batch over many
  DBs **must** pass distinct ids or column types leak across cases.
- There are **two different `FanoutFinding` classes** with disjoint fields (`grain_guard.py:40` vs
  `fanout.py:38`). An adapter that conflates them will produce wrong detail payloads.

**Flag** none (library only, no behaviour change) · **Tests** ~30 · **Decision gate:** the evaluator
set must reproduce `routers/query.py`'s existing `/query/validate` output on a fixture corpus before
that endpoint is refactored onto it. If it cannot, the adapters are wrong and the endpoint stays.

---

## PR-E3 — Suites, runs, and the consolidation

**Scope**

- **Store** following `verify/verdicts.py` exactly: `resolve_db_path("AUGHOR_EVALS_DB", data/evals.db)`,
  `org_id` from `current_org_id()` on every row **and every WHERE**, `Migration` list, clamped limits.
  (Note `evals/ratchet.py`'s `data/eval_baseline.db` has **no org column**, so it cannot back a
  product surface — but its `summarize` / `compare_to_baseline` / `persist_run` / `set_baseline` logic
  is directly reusable.)
- **Runner** = `packs/evalrunner.run_pack_evals`'s batch-with-injected-target shape, generalised:
  `suite = cases × targets × evaluators`, with **N-iteration replication**, **per-case causal
  attribution** (which evaluators touched this case; did its verdict flip), and **stable-win vs flaky**
  classification. This is the Spider discipline, in product form.
- **Targets** (all verified callable in-process):
  - ask → `build_ask_stream(req, request=None)` — documented and verified safe
  - investigate → `agent/graph.py:326 run_investigation(question, conn, on_node=…)`, with
    `build_graph_generic` + the `investigations.py:2639-2669` state block when full parity is needed
  - brief → `knowledge/briefing.py:312 generate_narrative(...)`, already used headlessly in
    `tests/unit/test_briefing_triage.py`
- **Scoring** generalises `user_agents/quality.py::results_match` — the one execution-grounded scorer we
  already trust — plus `evals/sql_accuracy.py::score_single`'s multi-reference best-of-wins for SQL cases.
- **Consolidation** (the point of the PR):
  - absorb `/semantic/{conn}/benchmarks` — **zero records exist**, so migration is free; retarget its
    shipped UI at the new store and delete the string-matching scorer and the context-blanking runner
  - fix `POST /eval/run`: gate it, drop the dead `by_category` param, remove the `live=False` hardcode,
    and stop reading a CWD-relative path out of an unpackaged directory
  - keep `golden_sql_expanded.jsonl` + the hermetic CI gate exactly as they are — load-bearing, untouched
  - adopt `packs/evalgate`'s `ActivationDecision` shape as the run verdict
- **Gate every route on `Capability.EVAL_SUITE`** — lighting up the capability we already sell.

**Flag** `evals.suites` (default off) · **Tests** ~35 · **Decision gate:** a suite of the 53 golden
cases run through the new runner must reproduce the ratchet's ~65% within noise. A different number
means the runner is measuring something other than the product, and shipping it would launder a
measurement bug into a baseline.

---

## PR-E4 — Per-run overrides: grid experiments (and the P7 bakeoff)

**What already exists.** `provider.set_run_model()` (`:108`) is a contextvar that propagates into
worker threads via `ContextThreadPoolExecutor` and is already used in production by
`kernel/jobs.py:219-227` for per-agent models. Model-pinning per run is **done**.

**What must be built**

- **Flag overrides per run.** `flags.flag_enabled` (`:438`) reads Ledger-KV then env — both
  process-global, no contextvar. A `ContextVar[dict[str,bool]]` consulted first, plus a
  `flag_overrides(**kw)` context manager, is ~15 lines and behaviour-preserving (the module already
  re-reads per call). **Caveat that must be tested:** graph-topology flags are read at *compile* time
  (`graph.py:128`, `:140`, `:229`), so the override has to wrap `build_graph_generic`, not just the run.
- **Temperature floor per run.** Default is **0.1, not 0.0** (`provider.py:434`), and the deep path's
  spine calls never pass it (`investigate.py:3220/3251/3349/3382/3809/3823/3904/4029`). Add a contextvar
  consulted in `_complete_on`/`_stream_on`, and **pass temperature through the Anthropic kwargs**, which
  drop it entirely today (`:517-521`).
- **`AUGHOR_FALLBACK_DISABLED=1` mandatory** for any measured run — the silent fallback swaps the model
  mid-run. `run_golden.py:538` already defends this way; make it a runner precondition, not a convention.
- **Fixture pinning**: `samples/scenario.py::seed_scenario_db` is byte-reproducible (`random.Random(42)`,
  no global RNG) and `scenario_summary` returns closed-form ground truth usable as assertion constants.
  Register via `registry.add_connection(name, "duckdb", path)` (proven in
  `tests/integration/test_golden_reference.py:26-44`); local DuckDB files open `read_only=True`
  (`connection.py:694`) so a run cannot mutate the fixture. Stamp `snapshot.data_version()` per run to
  **prove the fixture did not move**.
- **Port the frozen-semantics guard.** `run_golden._assert_frozen_semantics` (`:492`) aborts on a
  connection polluted by exploration/ontology drift. This is the #1 measurement confound and the
  existing best practice; it belongs in the product runner.

**Constraint to design around:** `AUGHOR_LLM_MAX_CONCURRENCY` defaults to **4** and the semaphore is
process-wide, keyed by base URL, held for the whole streaming call. Intra-run fan-out competes with
cross-run parallelism for the same 4 slots. N×K grids need either a raised cap or subprocess isolation
(the `model_bakeoff.py:236` precedent, which also gives per-cell `AUGHOR_SYSTEM_DB` isolation).

**Flag** `evals.experiments` (default off) · **Tests** ~25 · **Decision gate:** run the identical cell
three times and confirm the flag/model overrides actually took effect *per run* (assert on the recorded
config in `session_events`, not on the outcome). Per `verify-features-actually-ran`, an override that
silently no-ops looks exactly like "the variant didn't help."

---

## PR-E5 — The Evals surface

Follows the frontend recipe verbatim: `EvalsWorkspace` copied from `OperationsWorkspace.tsx` (keep-alive
layers so a running suite survives tab switches), `EvalSuitesPanel` on the `MonitorsPanel` skeleton
(list / in-place form view / `MiniStatRow` summary / `EmptyState`), `EvalRunPanel` driven by
`subscribeKernelEvents({kinds:["eval.","job.state"]})` with the customary 60 s fallback interval.

Results grid uses `AugTable` with `StatusChip` hues (`positive`/`negative`/`caution`/`muted`/`info`);
trend via `InvestigationChart columns={["run_at","pass_rate"]}`; per-case comparison via
`Chart chartType="grouped_bar" columnUnits={{pass_rate:"percent"}}`.

**Three CI gates to respect, not discover:** `npm run gen:api` must be run and `web/lib/api.gen.ts`
committed (CI diffs it); the raw-`<button>` ratchet sits at 73, so use `<Button>`; and do **not** copy
`MonitorsPanel`'s `var(--r2)`-as-a-colour bug (that is `task_e51a2fa2`, filed separately). Add
`"eval.suite": "Evaluation Suite"` to `upsell.ts` `FEATURE_LABELS`, which currently falls back to a
prettified guess.

**Tests** ~12 · **Decision gate:** the panel must render a real run end-to-end against the local fixture
before merge. No screenshots of stubbed data.

---

## PR-E6 — "Add as test case" + the promotion gate

The on-ramp that makes the whole arc compound, and the reason PR-E1 comes first.

- **From any receipt or trace → seed a case.** A one-click affordance on `TrustReceipt` and on a
  session-log trace view: capture question, connection, scope, resolved flags/model, executed SQL and
  the observed result as an `EvalCase`. This is Foundry's single best evals affordance, and after PR-E1
  we have every field it needs.
- **Evals as a promotion gate, not a report** — generalising `packs/evalgate.evaluate_activation`.
  The immediate consumer is already waiting: **four flags are ON in the live ledger but default-OFF in
  code** (`chart.exhibit_grammar`, `intake.loss_signals`, `lens.decision_grade`, `report.argument_style`),
  so a fresh clone and CI get none of it, and `ask.brief_context` / `ask.conversation_context` are
  soaking with no defined exit criterion. Make "graduate a flag" mean "its suite passes at or above
  baseline", with the decision recorded and receipted.

**Flag** none (uses `evals.suites`) · **Tests** ~15 · **Decision gate:** graduate exactly one real flag
through the gate before declaring the arc complete. A promotion gate that has never promoted anything
is a demo.

---

## Sequencing

```
PR-E1 (session log) ─┐
                     ├─→ PR-E3 (suites + consolidation) ─┬─→ PR-E4 (grid/experiments)
PR-E2 (evaluators) ──┘                                   ├─→ PR-E5 (surface)
                                                          └─→ PR-E6 (add-as-case + gate)
```

E1 and E2 are independent and can be stacked or parallel. E3 is the keystone. E4 and E5 are independent
of each other. E6 lands last because it consumes all of them.

**Arc total ≈ 135 tests.** Every PR is independently valuable: E1 fixes real observability blindness,
E2 unifies six guard shapes and can supersede `/query/validate`, E3 collapses five eval surfaces into
one, E4 finally executes the P7 bakeoff as a reusable feature rather than a script, E5 ships the UI,
E6 closes the loop.

**Stacked-merge discipline** (learned the hard way, see memory): retarget the child PR *before*
deleting a merged base, and verify the CI run SHA equals the head SHA before merging a retargeted PR.

---

## Risks

1. **Overclaiming reproducibility.** No seed, no response cache, Anthropic drops temperature. Every
   number this arc produces is a *band*, not a point. The UI must show the band; a single-run percentage
   would be a lie the product tells itself.
2. **Becoming surface #6.** If PR-E3 ships without absorbing the benchmarks router and fixing
   `/eval/run`, we have made the problem worse. Consolidation is the deliverable, not a nice-to-have.
3. **Measurement cost.** Suites × cases × N reps × grid cells hits a 4-slot LLM semaphore. Publish the
   projected call count and wall-clock in the run dialog *before* the user hits go.
4. **Session-log volume.** No retention exists for any observability table today. Ship the policy in E1.
5. **The `preflight_repair` LLM leak.** A "deterministic" evaluator that quietly calls a model would
   corrupt every baseline in the arc. Explicitly excluded and tested for.
