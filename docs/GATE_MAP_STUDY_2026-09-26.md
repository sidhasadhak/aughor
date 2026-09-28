# The gate map — which inputs and outputs pass which gates (study, 2026-09-26)

> **Why now.** The user, after theLook's Units Sold watch failed 2,283 times on BigQuery: *"we have built very good
> core engines, some very strong SQL guards, lots of quality gates — but we need to know which of the inputs and
> outputs go through which of the gates. This is critical because this overall flow, the robust mechanism, is the
> unique selling point of our platform. The user should be confident that if there is an input, whatever the level
> of error it may have, it will go through several gates, the core engine, the quality parameters, and the output
> will be less likely to be an error."* This document is the measurement, then the proposal. It was measured
> against the code on `main` at `c4d058c5` plus the hotfix `3692c15e`, not against the roadmap's prose.

## 1 · The gates that exist, as the code applies them

Every statement that reaches a customer warehouse goes through **the base door**, `DatabaseConnection._run`
(`aughor/db/connection.py`), in this order:

| # | step | what it does | who is exempt |
|---|------|--------------|---------------|
| 1 | `_validate` | parses the statement **in the connection's own dialect** (`sqlglot`, RAISE); refuses what does not parse; refuses non-SELECT unless the label is a metadata label | nothing |
| 2 | `_security_pre` | `SafetyChecker` (mutation, injection, exfiltration shapes) and an **audit row** | any label that is a dunder (`__profiler__`, `__monitor__`, …) or in `_INTERNAL_HYPO_IDS` — "platform plumbing, never block or audit"; a hand-listed exception set (`_INTERNAL_HYPO_IDS`' complement) forces genuine data activity back through |
| 3 | `enforce_row_policy` | injects the principal's RBAC row filters (`sql/rls.py`), in DuckDB form on transpile engines and in the native dialect on native engines | connections with no row policy |
| 4 | `translate` | **transpile engines only** (DuckDB, Postgres, the file and API connectors): rewrites `read=duckdb → write=<dialect>` | **native engines skip it**: BigQuery, Snowflake, MySQL, Exasol run the statement exactly as written (`writes_native_sql = True`) |
| 5 | `_run` | executes with the row cap (`MAX_ROWS`, or `execute_bounded`'s) | — |
| 6 | `_security_post` | PII redaction, the row budget, the agent's guardrail policy, the audit row of what was returned | the same internal labels |

On top of the base door sits **the guard battery door**, `execute_guarded` (`aughor/sql/executor.py`): `preflight_harden`
(de-fan, deterministic pre-repair) → `trust.verify` (scope: the schema the caller declared; **blocks** with `[BLOCKED]`)
→ the base door → join value-domain guard → filter value-domain guard → id-arithmetic guard → zero-row diagnosis →
E1 live trust checks → one deterministic repair, then one LLM repair when the caller supplies a fix prompt. Every
finding becomes a **caveat on the result** and a **guard receipt** (`GuardVerdicts`, through
`kernel/registries/execution_hooks.py`), which the answer envelope carries and the run label (TJ-3) reads.

Beside them: **the safety door for a person's own SQL**, `gate_user_sql` — `SafetyChecker` + audit on the raw text,
before any cache or wrapping (`/query/run`, the federated planner, the monitors router, the host contract).

And one **seam that is not a door**: `native_sql(db, sql)` (`aughor/db/dialects.py`). Platform code writes probes and
series in DuckDB's dialect (double-quoted identifiers); on a native engine a double-quoted identifier is a **string
literal**. `native_sql` transpiles for native engines and returns the statement unchanged everywhere else. It is a
function a caller must remember to call. **That is the flaw this study is about**: the base door applies steps 1–6
to every statement whoever wrote it, but the one transformation that decides whether platform-written SQL *means
anything* on BigQuery lives outside the door, in the memory of each call site.

### The output gates

| output | gate | what it checks |
|--------|------|----------------|
| an answer to a person (web, Slack mention, MCP) | the envelope (`answer/envelope.py`): guard receipts + caveats travel with the number; `guards_clean` decides what the memory and the corpus may learn from; the re-check (`answer/recheck.py`) re-runs the statement later and records `changed / unchanged` | NOT the departure gate — an answer is read where it is asked; laws 1–8 govern what *leaves* |
| a Briefing (standing or range) | grounded numbers (every figure resolves to a statement and a cell), BR-3's "which days" labels, the range Briefing's `measured / unmeasured` with reasons | held lines at delivery (`briefing/delivery.py::line_holds`) |
| an outward send — a briefing delivery, a monitor alert, an agent alert, an action, a re-check to Slack | **the departure gate**, laws 1–8 (`govern/departure.py`): causal licence, ungrounded numerals, tie-out, re-measure, probation, the receipt on the ticket | the automation engine's Slack sends (`notifications/executor.py`) and every caller above |
| a metric definition | the definition report (`semantic/definition_report.py`): runs, declares, compares, pins; the statement rule (a whole SELECT), the grain | approval is a person's act |
| a monitor alert | the anti-flap debounce, the guarded monitor (`monitors/runner.py`), then the departure gate at notify | — |
| a cockpit card | `execute_guarded` on pin and on every run; a range run says what it covers | — |
| an export (PDF/PPTX of an investigation) | whatever the investigation's envelope carried; nothing new at export | headless charts are Vega-only (known) |

## 2 · The census — every place SQL reaches a warehouse

Measured by walking `aughor/` for label-first `execute` / `execute_bounded` / `rows` / `read_typed_rows` /
`execute_guarded` calls and `run_sql` closures, excluding the platform's own SQLite stores: **184 sites in 90
files**. A static window classifies 23 (18 through `native_sql`, 5 generating in the connection's dialect); the
other 161 were read one by one. The full table is §5; the findings are here.

Of the 184: **34 are the platform's own SQLite stores or docstring examples** (not a warehouse); **150 reach a
customer warehouse**. By how the dialect is handled:

| dialect handling | sites | what it means |
|---|---:|---|
| written for the engine by its author (a person's SQL, the model's SQL with the writer rules, a stored finding) | ~45 | correct by construction; the gates that matter are safety, audit and the guards |
| generated in the connection's dialect by sqlglot | ~30 | correct: `compile_object_query`, `measure_sql`, `scoped_statement`, `period_split`, the object doors, the fix prompts |
| translated at the call through `native_sql` | ~20 | correct: the explorer, the ontology probes, the settling and measurement runner, the keyed right reads, the monitor runner (after the hotfix) |
| **platform-written in DuckDB's dialect and sent as written** | **~40** | **the bug class** — works on DuckDB and Postgres because the door translates there, fails or lies on BigQuery, Snowflake, MySQL and Exasol |
| DuckDB-prompted model SQL sent as written | 2 | the ambiguity probe prompt says "a single DuckDB SQL query"; the business-profile trend SQL is re-emitted `dialect="duckdb"` at serve time |

The bug class, grouped by what it does on a native engine (every site in §5):

- **Fails loudly, on a schedule.** The monitor runner (fixed today, both paths). The Units Sold watch was the
  only site on a one-minute tick, which is why it alone made the Security page.
- **Fails silently, with the gate reporting green.** These are the ones that matter most for the question asked,
  because a gate that fails open is a gate the reader believes ran:
  - the **join value-domain guard** and the **filter value-domain guard** (`sql/join_guard.py:137, :189, :265,
    :766`) — DuckDB `USING SAMPLE`, `CAST … AS VARCHAR`, `regexp_replace(…,'g')`, double-quoted identifiers; on an
    error they `tolerate` and return None with the words *"join allowed to proceed"*. On BigQuery the join guard
    inside `execute_guarded`, the chat path and `/query/validate` never runs, and the E1 checks that read it
    report clean;
  - the **grain probe** (`sql/validation.py:93`, `trust/__init__.py:125`, `evals/probe.py:28` — one builder,
    `sql/grain_guard.py:121`): quotes stripped, keys joined with `||`;
  - the **snapshot signature** (`db/snapshot.py:49`): `data_version` is None on native engines, so revalidation's
    `data_moved` detection is off there;
  - **re-anchoring a monitor's window** (`monitors/window.py:59`): the DuckDB-quoted SQL parsed as BigQuery reads
    the column as a literal and the rewrite silently does nothing;
  - the **ambiguity probes** (`routers/investigations.py:2318`): the model is told "DuckDB"; on a native engine
    they error and the clarify gate never fires;
  - the **metric pin and clarify probes** (`agent/investigate.py:5477, :5591`): a DuckDB-written governed formula
    fails and the pin is skipped;
  - **answer resolution** (`semantic/answer_resolution.py:626`): `db.rows` turns an error into `[]`, which reads
    as "absent" — a false abstain;
  - the **events scan**, the **catalog samples**, the **cross-source reconcile** (`tools/events.py:133`,
    `tools/data_catalog.py:249, :326`, `connectors/remote_join.py:152`): empty results, no error;
  - the **profiler on Exasol** (`tools/profiler.py`, eight sites): the transpiling wrapper is keyed on the dialect
    name, not on `writes_native_sql`, and Exasol declares `postgres` while executing natively.
- **Silently wrong.** `agent/investigate.py:553`: `SELECT "{a}", "{b}", COUNT(*) …` groups two string literals on
  BigQuery — one row, no error, and the zero-row check does not trip. The scan probes (`agent/nodes.py:449–479`)
  quote `schema.table` as one identifier, wrong on every engine for a qualified name. The ratio-grain and
  global-ratio probes (`agent/investigate.py:3096, :3455`), the analyst's value lookup (`agent/analyst.py:290`),
  the costume probe (`explorer/verify.py:273`), the ontology validator's model fragments
  (`ontology/validator.py:53, :86, :87`), the business-profile trend SQL (`routers/exploration.py:637, :644`),
  the metric value door (`semantic/metrics.py:626`, translate-engine-only) and `ALTER COLUMN`
  (`routers/connections.py:735`, which reports `applied: true` whatever the engine said).
- **Dead on every engine, found by the census rather than by an incident.** `memory/skills.py:372` and
  `routers/ontology.py:3516` prefix `EXPLAIN`, which `_validate` refuses except under the workbench label, so
  auto-crystallised skills never save; `overview/build.py:234` sends `SUMMARIZE`, which `_validate` refuses too.

**The audit is by label, and the label lies both ways.**

- *Audit gaps* — user, model or stored SQL over customer data that leaves no audit row and skips PII redaction,
  because its label is a dunder or on the internal allowlist: the departure re-measure that decides a send
  (`__departure__`), the answer re-check whose old and new values are then written into a message to a person
  (`__answer_recheck__`), the range Briefing's governed-metric runs (`__brief_period__`, while its sibling
  `__brief_metric_move__` is audited), the exploration retry with the model's repaired SQL (`__retry__`), the
  bulk read of a person's own SQL (`__bulk__`, and the ConnectorX path skips the door entirely), the semantic
  columns probe over a person's SQL (`__semantic_cols__`), trusted-query verification, a metric's tie-out and
  freshness SQL, the as-of replay (`__asof__`), the benchmark's model SQL (`benchmark`), the skill dry run, and —
  for query-backed ontology types — a person's keyed SELECT inside seven probe labels. Two more skip redaction on
  rows a person sees: `sample` and `__distinct__`; `_catalog` puts unredacted sample rows into the model's prompt.
- *Audit noise* — platform plumbing under a data label, so the page counts probes as activity: the intake's four
  probes, the measure-grain probe (up to 24 per connection), the costume probe, the skill dry run.
- *Labels the model chooses* — `agent/explore.py` and `agent/nodes.py` execute under ids the model emits
  (`Q1`, `h.id`); a dunder-shaped id would skip safety and audit.

**The parse step is not applied on native engines.** `_validate` (SELECT-only, parse in the dialect) runs in the
built-in DuckDB and Postgres `_run` only; BigQuery, Snowflake, MySQL, Exasol and the file and API connectors call
safety, the row policy and post-exec, but not it. On those engines the warehouse's own parser is the only parser.

**What went right, and why.** Every site that ran clean on theLook in the audit window uses one of three
disciplines: the model writes for the engine under the writer rules; sqlglot renders in the engine's dialect; or
`native_sql` translates at the call. The disciplines are sound. What is missing is that nothing makes a site
choose one.


## 3 · Live exposure, theLook (BigQuery), from the security audit

Read from `GET /security/audit` on connection `8233e4fd` on 2026-09-26, the newest 2,000 statements (the page's
totals: 5,841 statements, 2,288 errors, 140 suspicious, 0 blocked, 630 PII redactions).

| door / label | statements | errors | error rate |
|---|---:|---:|---:|
| `__monitor__` (the monitor runner, the automation engine's one-minute tick) | 1,663 | 1,623 | 97.6% |
| `cb2_review` (the settling and measurement runner, through `native_sql`) | 90 | 0 | 0% |
| `card:…` (cockpit cards, through `execute_guarded`) | 58 | 0 | 0% |
| `query_builder` (a person's SQL, through `gate_user_sql`) | 58 | 0 | 0% |
| `__explorer__` (the explorer, through `native_sql`) | 47 | 0 | 0% |
| `decomposition`, `converse`, `query_workbench`, `baseline`, the intake probes, the eval probes, `__brief_metric_move__`, an automation | 84 | 2 | 2.4% |

1,614 of the 1,623 monitor errors carry one text: `400 Invalid date: 'created_at'`. **One door that skipped one
seam produced 99.9% of the connection's errors**, on a schedule nobody meant (the user's automation carried no
schedule, so the engine evaluated its condition every tick). Every door that goes through `native_sql` or
`execute_guarded` ran clean on the same warehouse in the same window. The runner now translates (hotfix
`3692c15e`); the receipt after the restart is two clean runs of 135 rows at 20:59.

Two things the audit itself shows about the audit: `__monitor__` is a dunder label and was audited anyway, because
it sits in the hand-listed exception set that forces genuine data activity back through the gate — the list is
doing its job, by hand; and a reader of the page cannot tell which of the 5,841 statements were *not* audited,
because the exempt ones leave no row at all.


## 4 · What the map says

1. **The gates are strong and the doors are few — but the dialect is nobody's.** Steps 1–6 are applied by the
   door to every statement. Translation is applied by whoever remembers `native_sql`. Six tests exist for it, and
   every one was written after a live failure: the explorer's 42 September failures, the intake's 222 of 4,409,
   the settling sampler, the object sources, the BigQuery timestamp clash, the writer rules. The monitor runner
   was the seventh incident. A gate enforced per incident is not a gate; it is a scar.
2. **Native engines are the only place the flaw shows.** On DuckDB and Postgres the door translates (step 4), so
   a site that forgets `native_sql` still works. theLook is BigQuery. Every "works on the samples, fails on
   theLook" report of this class is the same defect.
3. **Audit exemption is by label spelling.** A dunder label skips safety and audit. The exception list that forces
   genuine data activity back through is hand-listed, and the census shows labels chosen for history, not for
   what the statement is. A person cannot tell from the audit page which statements were never audited.
4. **A guard that fails open reports green.** The join and filter value-domain guards, the grain probe, the
   snapshot signature, the ambiguity probes and the metric pin all `tolerate` their own failure and return "nothing
   found". On a native engine they fail on the dialect and the reader sees a clean result. The falsifier the user
   wants — "whatever the error, it went through several gates" — is false on BigQuery for exactly the gates that
   catch a wrong join, and nothing on the page says so.
5. **The parse step and the redaction step depend on the engine and the label, not on the statement.** Native
   engines skip `_validate`; internal labels skip PII redaction on rows a person sees (`sample`, `__distinct__`)
   and on rows the model reads (`_catalog`).
6. **The receipt does not name the doors.** An answer carries guard receipts (what fired) but not which doors the
   statement passed (validated, audited, row-filtered, translated, guarded). The confidence the user asks for —
   "it went through several gates" — is true and unsaid.

## 5 · The proposal — make the door own the dialect, and make the path a receipt

- **P1 — the statement declares its dialect; the door translates.** `execute(label, sql, *, sql_dialect=None)`:
  `"duckdb"` from platform code (probes, series, measures) makes the base door translate for native engines at
  step 4, where transpile engines already do; `None` means "written for this engine" (the model's and a person's
  SQL). `native_sql` becomes the door's own step, and a caller that forgets is a caller that passed nothing —
  which the census ratchet below then names. Migration: the `none` sites in §2 first, then every
  `platform-fstring` site, mechanically.
- **P2 — the census is a ratchet.** `tests/unit/test_sql_door_census.py` walks the same regex over `aughor/`
  and holds `docs/SQL_DOORS.json`: every site classified (door, author, dialect handling, gates). A new site
  that is not in the file fails the test with the row to add; a site whose classification is `none` may only
  fall. This is the shape the repo already trusts (frame parity, the tool-prose ratchet, the private-import
  ratchet): a hand-listed baseline that can shrink and never grow.
- **P3 — the path is a receipt.** `QueryResult.doors: list[str]` — the base door appends what it applied
  (`validated:bigquery`, `audited` or `internal:<label>`, `row-filtered`, `translated:duckdb→bigquery`, `guarded`),
  the guard door appends its own. The envelope carries it, the trajectory's `step` shows it, Spotlight's
  `explain` can say it: *"this number passed six gates; here they are."* That is the sentence the user wants a
  reader to be able to trust, and it costs a list.
- **P4 — audit by what the statement is, not by how the label is spelled.** The exemption becomes a property
  of the call (`internal=True`) that only platform plumbing sets; a label's spelling stops deciding whether a
  statement over customer data is audited.

Effort: P1 two days plus the migration by census; P2 a day; P3 a day; P4 a day plus the hand-listed set's
retirement. The receipt for the arc is the census ratchet at zero `none` sites and a Spotlight answer that
names its gates on theLook.

## 5 · Appendix — the census, site by site

Three read-only passes over the 161 sites a static window could not classify, each row read at its source
(door · label · who wrote the SQL · how the dialect is handled · which gates apply). `validate†` means the parse
step runs only in the built-in DuckDB and Postgres `_run`; the native connectors call `security_pre`, the row policy
and `security_post` but not `_validate`. Rows marked `sqlite-store` are the platform's own stores and are listed
only to show they were looked at.

### 5.1 · agent/, answer/, automations/, connectors/, custom_agents/, db/

| site | door | label | SQL author | dialect handling | gates | note |
|---|---|---|---|---|---|---|
| agent/analyst.py:283 | execute_guarded | `analyst_premise_check` / `analyst_z_score` | premise: platform-fstring over intake fields; z-score: model | premise: none (portable so far); z-score: native-by-author | safety+audit, rls, validate†, guards | no `schema` and no fix template passed: no preflight, no LLM repair |
| agent/analyst.py:290 | execute | `__analyst_value_lookup__` / `__analyst_profile_column__` | platform-fstring | **none** — `_qident` double-quotes; `LOWER(CAST({_qident(col)} AS VARCHAR))` | dunder, rls, validate† | **bug class** |
| agent/benchmarks.py:255 | execute | `benchmark` (in `_INTERNAL_HYPO_IDS`) | model (coder + writer_rules) | native-by-author | internal-id: no safety, no audit, no post | **audit gap**: model SQL, no gate at all, not guarded |
| agent/converse_tools.py:54, :81 | execute_guarded | `converse` | model (tool arg) | native-by-author | safety+audit, rls, validate†, guards (no preflight/LLM retry) | the converse prompt carries no `writer_rules` |
| agent/converse_tools.py:153 | execute_guarded | `objects` | platform-sqlglot(dialect=conn.dialect) | generated-in-dialect | safety+audit, rls, validate†, guards | — |
| agent/explore.py:706, :768, :804 | execute | `$subq.id` (model-emitted "Q1…") | model (no dialect in the plan prompt; the fix prompt has it) | native-by-author | safety+audit, rls, validate†; inline preflight + value-domain guards | a model-chosen label: a dunder-shaped id would skip safety and audit |
| agent/federated_planner.py:89 | execute | `__fed_cols__` | model step SQL in a portable `LIMIT 0` wrapper | native-by-author | dunder, rls, validate†; `gate_user_sql` earlier | model SQL under a dunder label, covered only by the caller's pre-gate |
| agent/federated_planner.py:173 | execute_bounded | `__fed_driver__` | model | native-by-author | dunder, rls, validate†; gate_user_sql before; security_post on the join | plumbing label by design |
| agent/investigate.py:1780 | execute_guarded | `$phase_id` | mixed: model plan SQL; platform-fstring (:553, :134, :7106); stored metric | model: native; platform: **none** — :553 `SELECT "{a}", "{b}", COUNT(*) …` | safety+audit, rls, validate†, guards + one LLM repair | **silently wrong on BigQuery**: two string literals group to one row, no error, the zero-row check does not trip |
| agent/investigate.py:3096 | execute | `__ratio_grain_probe__` | platform-fstring (sql/ratio_grain.py) | **none** — `d."{seg}"`, `_qt` double-quotes, `IS NOT DISTINCT FROM` | dunder, rls, validate† | **bug class** |
| agent/investigate.py:3455 | execute | `__global_ratio_probe__` | platform-fstring | **none** — `SUM("{num_col}")` | dunder, rls, validate† | **bug class** |
| agent/investigate.py:4261, :5392 | execute | `intake_span`, `intake_unit_probe` | platform-fstring | none (unquoted, portable) | safety+audit, rls, validate† | audit noise; quotes stripped, so a reserved name breaks |
| agent/investigate.py:5477, :5591 | execute | `intake_metric_pin_probe`, `clarify_metric_probe` | platform wrapper around a stored governed formula | none | safety+audit, rls, validate† | a DuckDB-written governed formula fails on native engines, so the pin and the clarify gate **silently skip** |
| agent/investigate.py:6664, :8550 | execute | `__fanout_schema_probe__`, `__temporal_types__` | platform-fstring over INFORMATION_SCHEMA | none (unqualified) | dunder, rls, validate† | relies on BigQuery `default_dataset` |
| agent/investigate.py:7595, :8114, :8422, :8442 | execute | `__xsec_premise__`, `__xsec_base_rows__`, `__uniq_probe__`, `__card_probe__` | platform-fstring | none (portable today) | dunder, rls, validate† | — |
| agent/investigate.py:8128 | execute | `__xsec_scanned__` | platform-sqlglot(dialect=conn.dialect) over the finding's model SQL | generated-in-dialect | dunder, rls, validate† | the original run was audited; the re-scan is not |
| agent/nodes.py:449, :459, :468, :479 | execute | `scan` (internal id) | platform-fstring | **none** — `_q(name) = f'"{name}"'` quotes `schema.table` as ONE identifier; `MIN({dc})::VARCHAR` | internal-id: no safety, no audit | **bug class**, and wrong even on DuckDB for a qualified table |
| agent/nodes.py:887, :935, :974 | execute | `$h.id` (model-emitted) | model (`generate_sql(dialect=…)`, FIX prompt with dialect) | native-by-author | safety+audit, rls, validate†; inline preflight + guards | a model-chosen label (same exposure as explore.py) |
| answer/recheck.py:275, :276 | run_sql / execute | `__answer_recheck__` | stored (the answer's executed SQL) | native-by-author | dunder, rls, validate† | **audit gap**: no safety, no PII redaction, no audit — and old/new values and a missing row's values flow into the correction text sent to people |
| automations/probes.py:111 | execute_bounded | `__automation_probe__` | platform-fstring (table must match an identifier regex) | none (portable) | dunder, rls, validate† | — |
| connectors/api/base_sync.py:200, api/gsheets.py:198, federated.py:169, file/local_upload.py:1333, file/s3.py:145, warehouse/motherduck.py:55, mysql.py:65, snowflake.py:57 | the driver's bound execute | `$hypothesis_id` (`/query` source) | user (bound params) | native-by-author | safety+audit, rls, gate_user_sql; **no validate** | — |
| connectors/remote_join.py:152 | execute_bounded | `__remote_join__` | platform-fstring wrapping model or route SQL; `_qident` double-quotes | **none** — DuckDB-only reconcile templates (`regexp_replace(…,'g')`, `CAST AS VARCHAR`) | dunder, rls, validate†; caller's security_pre/post | **bug class**; its sibling `fetch_by_keys` (:344) uses `native_sql` |
| connectors/remote_join.py:344 | read_typed_rows | `__remote_join__` | platform-fstring | native_sql | dunder, rls, validate†; caller's security_pre/post | — |
| connectors/remote_join.py:392 | execute_bounded | `__remote_join_left__` | user (`/query/cross-source-join`) | native-by-author | dunder, rls, validate†; gate_user_sql before; security_post(also_read) | — |
| custom_agents/quality.py:267, :277 | execute | `__agent_eval_ref__`, `__agent_eval_gen__` (audited dunders) | stored user golden / model (writer_rules) | native-by-author | safety+audit, rls, validate† | the generated side is not guarded |
| db/connection.py:771 | execute (typed) | `$_source` (`query_builder` / `query_workbench`) | user | native-by-author | safety+audit, rls, validate†, gate_user_sql, cache | — |
| db/connection.py:900, :909 | rows / scalar (→ execute) | `$label` (default `__adapter__`) | caller-dependent | **caller-dependent** — `_scalar` sent DuckDB quoting until the hotfix's second half | label-dependent; errors swallowed to `[]` | the adapter does no dialect handling and its default label is a dunder |
| db/connection.py:938 | execute (ibis) | `$hypothesis_id` | platform (ibis compiles in the dialect) | generated-in-dialect | label-dependent | no callers — dead |
| db/connection.py:965, :1873, :1876 | execute (`bulk_read`) | `__bulk__` | user (`/query` `use_bulk`) | native-by-author; PG fallback translate-engine-only | dunder, rls, validate†, gate_user_sql before, cache | **audit gap**: user SQL under a dunder — no PII redaction, no budget, no audit row; the ConnectorX primary path skips execute entirely |
| db/connection.py:981 | read_typed_rows (→ execute_bounded) | `$hypothesis_id` (must be internal) | platform (remote_join; cross_source home plan) | native_sql / generated-in-dialect | dunder, rls, validate†; callers run security_pre/post | — |
| db/measure.py:21, :22 | run_sql / execute | `cb2_review` | platform canonical SQL (DuckDB-written) | native_sql | safety+audit, rls, validate† | platform measurement audited (matches the `__monitor__` policy) |
| db/snapshot.py:49 | execute | `__snapshot__` | platform-fstring, `_quote` double-quotes | **none** | dunder, rls | **bug class, fail-open**: `data_version` is None on native engines, so revalidate's `data_moved` detection is off there |
| db/snapshot.py:134 | execute | `__asof__` | stored finding SQL, rewritten `AT (VERSION => n)` | generated-in-dialect (DuckLake only) | dunder, rls, validate† | **audit gap**: the same finding runs audited as `__revalidate__`, its as-of replay not |
| actions/overlay.py, custom_agents/store.py, db/backend.py, db/matcache.py (docstring), connectors/file/local_upload.py:33 (docstring) | — | — | sqlite-store / not a call | — | — | not a warehouse |

### 5.2 · evals/, explorer/, feedback/, govern/, intake/, kernel/, knowledge/, lifecycle/, memory/, monitors/, obs/, ontology/, overview/, packs/, pipeline/

| site | door | label | SQL author | dialect handling | gates | note |
|---|---|---|---|---|---|---|
| evals/probe.py:28 | execute | `__eval_probe__` | platform-fstring (sql/grain_guard.py) | **none** — `COUNT(DISTINCT {keys joined by \|\|'-'\|\|})`, quoting dropped | dunder, rls, validate† | on MySQL `\|\|` is OR; BigQuery needs string operands |
| evals/targets.py:28 | execute | `eval.reference` / `eval.generated` | stored golden (suite author) / model | native-by-author | safety+audit, rls, validate† | not guarded |
| explorer/agent.py:684 | execute_guarded | `__explorer__` (audited dunder) | model (told the dialect) | generated-in-dialect | guards (no LLM retry), safety+audit, rls, validate† | correct; `native_sql` applied on the raw branch (:677) |
| explorer/agent.py:889, :944 | execute | `__explorer__` (audited) | platform-fstring (`date_trunc … ::VARCHAR`) | native_sql | safety+audit, rls, validate† | platform probe on an audited label, by design |
| explorer/fix_persist.py:119 | execute | `__fix_save__` (audited) | model (`SqlWriter.fix`, writer_rules) | generated-in-dialect | safety+audit, rls, validate† | repaired SQL stored as a finding **without** execute_guarded |
| explorer/revalidate.py:85, revalidate_live.py:68 | execute | `__revalidate__` (audited) | stored finding SQL (model) | native-by-author | safety+audit, rls, validate† | — |
| explorer/verify.py:273 | execute | `_verify_costume` (single underscore: not dunder, not internal) | platform-fstring (`costume_probe_sql`) | **none** — `"{esc}"`, `FILTER (WHERE …)`, `regexp_matches`, `VARCHAR` | safety+audit, rls, validate† | **bug class** (the exact shape of today's failure), and audit noise |
| govern/departure_basis.py:416 | execute | `__departure__` | stored investigation / finding SQL (model) | native-by-author | dunder, rls, validate† | **audit gap**: the re-measure that decides a send runs unaudited while `__revalidate__`, `__ground__`, `__brief_metric_move__` are audited |
| kernel/registries/execution_hooks.py:77 | — | — | docstring example | — | — | not a call |
| knowledge/period_brief.py:376, :381 | run_sql / execute (`connection_runner`) | `__brief_period__` | platform-sqlglot(dialect=db.dialect) over stored governed `chart_sql`; shared with ranges.py, recipes.py, reask.py | generated-in-dialect | cache (matcache) then dunder, rls, validate† | **audit gap**: governed-metric SQL re-run unaudited while its sibling `__brief_metric_move__` is audited; a cache hit executes nothing |
| lifecycle/mapper.py:42, :91 | execute | `process_map_nodes` / `_edges` (internal ids) | platform-fstring (unquoted) | none (portable while names need no quoting) | internal-id, rls, validate† | low risk |
| memory/skills.py:372 | execute | `auto_skill_dry_run` (not internal) | stored skill template + platform `EXPLAIN ` prefix | native-by-author | safety+audit, rls, validate† | **dead**: `_validate` refuses EXPLAIN except under `query_workbench` (verified: `Only SELECT is allowed, got Command`), so auto-crystallise never saves; BigQuery has no EXPLAIN |
| monitors/runner.py:34 | rows | `__monitor__` (audited) | stored monitor SQL (`daily_series_sql`, DuckDB-quoted) or governed metric SQL | native_sql (hotfix) | safety+audit, rls, validate† | `_scalar` (:73) was still bare — fixed in the same hotfix after this row was read |
| monitors/window.py:126 | execute | `__monitor_window__` (audited) | platform-fstring; table via `tbl.sql(dialect=db.dialect)`, column bare | generated-in-dialect (column unquoted) | safety+audit, rls, validate† | :59 parses DuckDB-quoted monitor SQL with `read=db.dialect`: on BigQuery the column reads as a literal and re-anchoring **silently does nothing** |
| ontology/backing.py:43, bindings.py:197, :225, declared.py:284, :328, display.py:115, sources.py:59 | execute / execute_bounded | `__backing_probe__`, `__binding_probe__`, `__link_probe__`, `__display_probe__`, `__source_keys__` | platform-fstring (`quote_ident`) + a `from_clause` that may embed a **person's keyed SELECT** | native_sql | dunder, rls, validate† | **audit gap for query-backed types**: a person's SELECT runs inside a dunder probe with no SafetyChecker and no audit, and `native_sql` reads it as DuckDB |
| ontology/bindings.py:731 | execute (typed) | `binding_columns` (non-dunder on purpose) | platform-fstring `SELECT * FROM {source} LIMIT 0` | native_sql | safety+audit, rls, validate† | — |
| ontology/business_rules.py:173, processes.py:413, :426, :640 | execute_bounded | `__process_probe__` | platform-sqlglot(dialect=home_db.dialect) (`compile_object_query`) | generated-in-dialect | dunder, rls, validate† | — |
| ontology/cardinality.py:72, lifecycle.py:61 | execute | `__cardinality_probe__`, `__lifecycle_probe__` | platform-fstring (`quote_ident`) | native_sql | dunder, rls, validate† | — |
| ontology/expressions.py:129, :131 | execute / execute_bounded | `__ontology_validate__` | platform wrapper over sqlglot(dialect) + a **person-authored expression** | generated-in-dialect (wrapper ANSI, `g.{probe}` unquoted) | dunder, rls, validate† | a person's formula under a dunder label |
| ontology/validator.py:53, :86, :87 | execute | `__ontology_validate__` | platform wrapper over **model-written enricher fragments** (the prompt names no dialect) | **none** | dunder, rls, validate† | LLM text spliced into SQL with no SafetyChecker; on native engines not even `_validate` |
| overview/build.py:234 | execute | `__overview__` | platform-fstring: `SUMMARIZE SELECT * FROM {qt}` | **none** (DuckDB-only) | dunder, rls, validate† | **dead**: `_validate` refuses SUMMARIZE everywhere (verified: `Only SELECT is allowed, got Summarize`), so `_profile` gets no rows on any connector |
| packs/gate4.py:288 | execute | `__gate4_*__` | stored pack SQL | n/a | dunder | a temp DuckDB the platform builds from the pack dataset, not a customer warehouse |
| pipeline/pipeline.py:85 | execute (`SqlCapability`) | `capability.data` | model (`generate_sql(dialect=scope.dialect)`) | generated-in-dialect | trust verify (validate phase), safety+audit, rls, validate† | bypasses execute_guarded |
| evals/store.py, feedback/verdicts.py, govern/tag_store.py, intake/store.py, kernel/ledger.py (×7), obs/agent_alert_store.py (×2), evals/probe.py:21 (docstring) | — | — | sqlite-store / not a call | — | — | not a warehouse |

### 5.3 · routers/, semantic/, sql/, tools/, trust/

| site | door | label | SQL author | dialect handling | gates | note |
|---|---|---|---|---|---|---|
| routers/catalog.py:86 | execute | `__catalog__` | platform literal (`current_database()`), DuckDB branch only | generated-in-dialect | dunder, rls, validate† | — |
| routers/connections.py:491, :527, :651 | execute | `freshness`, `sample`, `columns` (internal ids) | platform-fstring via `ident_quote` / `qualified_table` | generated-in-dialect | internal-id (no safety, no audit, **no PII redaction**), rls, validate† | `sample` returns raw rows to the UI unredacted |
| routers/connections.py:735 | execute | `alter_column` (internal id) | platform-fstring `ALTER TABLE "s"."t" ALTER COLUMN "c" TYPE …` | **none** | internal-id, rls, validate† | **broken**: `result.error` never checked, the endpoint answers `applied: true`; `_validate` refuses ALTER on DuckDB/PG, BigQuery errors on the quotes, native connectors send the DDL |
| routers/dashboard.py:177 | execute_guarded | `pin:{id}` / `pin-query` | stored finding SQL (model) or a person's builder SQL | native-by-author | safety+audit, rls, validate†, guards | pin-query skips `gate_user_sql`; the unwrapped SQL still meets `_security_pre` |
| routers/dashboard.py:441 | execute_guarded | `card:{id}` | stored card SQL; with a range, re-cut by `scoped_statement(dialect=conn.dialect)` | native-by-author + generated-in-dialect | safety+audit, rls, validate†, guards (no schema → no preflight) | — |
| routers/exploration.py:637, :644 | run_sql / execute | `__brief_metric_move__` (audited dunder) | stored business-profile `chart_sql` (model, prompted "runnable DuckDB"), re-emitted `outer.sql(dialect="duckdb")` at serve time | **translate-engine-only** | safety+audit, rls, validate†, cache | the standing Briefing's metric moves reach native engines untranslated; failures swallowed per metric (0 errors in theLook's window, 2 runs) |
| routers/exploration.py:1120 | execute_guarded | `__retry__` | model (`SqlWriter.fix`, writer_rules) | generated-in-dialect | dunder (not in the audited set), rls, validate†, guards | **audit gap**: repaired SQL, rows to the client, no safety, no audit, no redaction |
| routers/exploration.py:1650 | execute | `__ground__` (audited) | stored finding SQL (model) | native-by-author | safety+audit, rls, validate† | unguarded replay on purpose |
| routers/investigations.py:1445 | execute | `chat` | model (+ preflight repairs rendered in db.dialect) | generated-in-dialect | safety+audit, rls, validate†; its own inline guard battery | the quick path does not use `execute_guarded` |
| routers/investigations.py:2318 | execute | `ambiguity_probe` | model, prompted **"a single DuckDB SQL query"** | translate-engine-only | safety+audit, rls, validate† | on native engines the probes error and the clarify gate **silently never fires** |
| routers/objects.py:420, :471 | execute_guarded | `objects` | platform-sqlglot(dialect=db.dialect) | generated-in-dialect | safety+audit, rls, validate†, guards | — |
| routers/ontology.py:3265 | execute | `lifecycle_counts` (internal id) | platform-fstring, bare identifiers | none (portable while names need no quoting) | internal-id, rls, validate† | — |
| routers/ontology.py:3516 | execute | `skill_dry_run` (internal id) | stored/model skill SQL under a platform `EXPLAIN` | **none** | internal-id, rls, validate† | **dead** on DuckDB/PG (`_validate` refuses EXPLAIN outside the workbench label); BigQuery has no EXPLAIN |
| routers/query.py:421, :576 | execute | `$_source` (`query_builder` / `query_workbench`), `semantic_operator` | user, wrapped `SELECT * FROM (…) __q LIMIT n` | native-by-author | gate_user_sql, safety+audit, rls, validate†, cache | the reference door for a person's SQL |
| routers/query.py:804 | execute | `__semantic_cols__` | user, wrapped | native-by-author | dunder, rls, validate† | **audit gap**: a person's SQL with no SafetyChecker and no audit; the sibling at :553 gates |
| routers/query.py:1523 | execute | `__distinct__` | platform-fstring (`ident_quote`) | generated-in-dialect | dunder, rls, validate† | raw column values to the filter picker, **unredacted** |
| semantic/answer_resolution.py:626 | rows | `__resolve__` | platform-fstring, `CAST({col} AS VARCHAR)` | **none** | dunder, rls, validate† | `rows()` turns an error into `[]` → a **false "absent"** on native engines |
| semantic/cross_source.py:336 | read_typed_rows | `__objects_home__` | platform-sqlglot(dialect=home) | generated-in-dialect | dunder by design; `security_pre` per connection + `security_post` on the answer | — |
| semantic/measure_grain.py:274 | execute | `measure_grain` | platform-fstring, bare identifiers | none | safety+audit, rls, validate† | audit noise: up to 24 probes per connection |
| semantic/metrics.py:626 | execute | `__metric_value__` | stored governed metric, wrapped by `as_statement` (DuckDB assumed) | **translate-engine-only** | dunder, rls, validate† | a person's metric SQL, unaudited and never translated for native engines; also called from the automation engine |
| semantic/metrics.py:684, :686 | execute_bounded / execute | `__metric_tieout__`, `__metric_freshness__` | stored user quality tests / freshness SQL | native-by-author | dunder, rls, validate† | **audit gap**: a person's SQL under dunder labels |
| semantic/object_context.py:117, object_instances.py:275 | execute | `object_metric`, `object_instance` | platform-sqlglot(dialect=db.dialect) | generated-in-dialect | safety+audit, rls, validate† | — |
| semantic/object_instances.py:98 | execute | `object_instance` | platform-fstring (`quote_ident`) | native_sql | safety+audit, rls, validate† | the reference pattern |
| semantic/trusted_verify.py:64 | execute_bounded | `__trusted_verify__` | user (imported trusted-query seed) | native-by-author | dunder, rls, validate†; `trust.verify` first | **audit gap** |
| sql/executor.py:254, :388, :498 | execute | `$query_id` | the caller's SQL after preflight; the deterministic repair; the model's repair (fix prompt with dialect) | native-by-author / generated-in-dialect | the caller's label decides; guards, rls, validate† | — |
| sql/join_guard.py:137, :189, :265, :766 | execute | `__domain_probe__`, `__hll_overlap_probe__`, `__reconcile_probe__`, `__filter_sibling_cols__` | platform-fstring, double-quoted, `USING SAMPLE`, `CAST AS VARCHAR`, `regexp_replace(…,'g')` | **none** | dunder, rls, validate† | **the guards fail open**: an error is tolerated as "join allowed to proceed"; the sibling-column repair is dead on backtick engines; a failed overlap probe marks the edge VERIFIED |
| sql/join_guard.py:1028, :1041 | execute | `__coverage_probe__` | fragments of the executed query | native-by-author | dunder, rls, validate† | the FROM regex never matches quoted or backticked tables, so the check is skipped there |
| sql/trust_checks.py:284 | execute | `__trust_coltypes__` | platform literal over INFORMATION_SCHEMA | n/a (portable) | dunder, rls, validate† | — |
| sql/validation.py:93, trust/__init__.py:125 | execute | `__grain_probe__`, `__trust_grain__` | platform-fstring (`sql/grain_guard.py:121`), quotes stripped, keys joined with `\|\|` | **none** | dunder, rls, validate† | same builder as `evals/probe.py:28` |
| tools/data_catalog.py:249, :326 | execute | `_catalog` (internal id) | platform-fstring `DESCRIBE` / `PRAGMA table_info` (DuckDB-only) then INFORMATION_SCHEMA; `SELECT … LIMIT 5` with `"` quoting | **none** | internal-id (no redaction), rls, validate† | two failing round trips per table on native engines; samples come back empty there, and where they work they go **unredacted into the model's prompt** |
| tools/events.py:133 | execute | `__events_scan__` | platform-fstring `FROM "{table}"`, `CAST AS VARCHAR` | **none** | dunder, rls, validate† | the events table is never found on native engines (silent `[]`) |
| tools/profiler.py:955, :966, :1188 | execute | `__profiler__` | platform-fstring, DuckDB-only branches (`duckdb_tables()`, `SUMMARIZE`, `approx_count_distinct`) | generated-in-dialect (dispatched by dialect) | dunder, rls, validate† | — |
| tools/profiler.py:1136, :1186, :1342, :1348, :1479, :1515 | execute | `__profiler__` | platform-fstring, `_qt` double-quotes | via `_TranspilingConnection` (an inline copy of `native_sql`) | dunder, rls, validate† | **Exasol gap**: the wrapper is keyed on the dialect name, not `writes_native_sql`; sample rows unredacted into the profile |
| tools/profiler.py:1718, :1723 | execute / execute_bounded (wrapper) | `$label` | platform DuckDB SQL, `sqlglot.transpile(read="duckdb", write=…)` | native_sql-equivalent | dunder, rls, validate† | the same seam, reimplemented |
| semantic/ambiguity_ledger.py:289, :344 | — | — | sqlite-store | — | — | not a warehouse |

Legend for the three tables: `validate†` — the parse step runs only in the built-in DuckDB and Postgres `_run`;
`internal-id` — a non-dunder label on the hand-listed allowlist, exempt exactly like a dunder; `rls` — the row policy
applies on every connector and is a no-op without an identified user.

