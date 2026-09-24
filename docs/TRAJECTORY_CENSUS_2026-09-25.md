# The trajectory census — where Aughor stands against a trajectory-based learning system

*Measured 2026-09-24 and 2026-09-25 against `main` at `39e8cfb4` (#548) and the serving instance on port 8000. Every
store was opened read-only, no model call was made, and every row count is a floor (writes still in a WAL were not
read). Four read-only surveys of the code and the data, and every claim a conclusion rests on was re-checked by hand.
This is TJ-0 of Arc TJ (ROADMAP §3.47); the roadmap section restates what is load-bearing so it stands alone, and this
file holds the receipts.*

**The map.** The reference is the diagram *Post-Training to Agentic Learning for LLMs — Reasoning-First, Trajectory-Based
System* (ContextAI GmbH): eleven boxes in two phases, a shared-infrastructure strip, and one unified trajectory store.
Phase 1 is single-shot reasoning — a problem, intermediate steps, a final answer, a reward. Phase 2 is a multi-step agent
— a task, tool actions, observations, a final state, a reward. Both feed one store, and one loop turns: trajectories are
graded, selected, trained on, and the better model produces better trajectories. The diagram's own examples are a data
warehouse query and a data warehouse analysis with a chart, which is this platform's work.

**The reading in one sentence.** Aughor is a complete Phase 2 serving environment standing on a Phase 1 learning ledger
that is built and starved, with no training engine on either side; the loop at the top of the diagram has never turned
once, and what stands between here and it is volume, labels, and one store — not code.

---

## 0 · The eleven boxes, the strip and the store

| Diagram box | Aughor today | State |
|---|---|---|
| 1 Data and problem source | 139 hand-written question-to-SQL pairs over four connections (`evals/golden_sql_expanded.jsonl` 53, `evals/ablation_*.jsonl` 86), a 24-case Superstore suite and 5 theLook goldens in the evals plane, 12 trusted queries of which 1 is person-verified. Rich internal context (1,286 ontology doc files, a 264-table generated glossary, 282 pack patterns), but the pack knowledge base's vector collection holds 0 points. No synthetic problem generation. | Thin data, no generator |
| 2 Rollout engine | One trajectory per question on the live path. The self-consistency sampler (`aughor/agent/sql_consensus.py:100`) has no caller. Ablations, grids and bake-offs run several arms offline and keep outcomes, not trajectories. | Single-shot live |
| 3 Reasoning trajectory | Per model call: model, temperature, tokens, timings, caller, role. Prompts and responses only inside an operator capture window (3 of 1,744 calls). Logprobs nowhere (`aughor/judgment/seam.py:17-18`). Tool arguments and results never persisted. The explorer's step log (`data/episodes_*.jsonl`, 2,408 turns in 73 runs) is the only trajectory-shaped record and carries no model, reward or trace id. | Partial |
| 4 Verification and reward | Executable tests live: the dry-run repair loop, preflight repair, 337 guard fires kept. Constraints live: read-only, SQL safety, PII, budgets, the departure gate. Exact-answer match exists only in the eval harness, with two comparators that judge differently. No model judge of answer quality (dropped 2026-09-06). 5 human verdicts, none carrying SQL. No numeric reward on any live run. | Deterministic half live, reward absent |
| 5 Selection and transformation | Exporters for SFT, preference, golden, bronze and repair pairs (`aughor/learning/exporters.py`) with dedupe, PII scrub, org scope and a leak-proof split. Manual trigger only. Datasets hold 0, 0 and 5 rows; the directory their blobs point at does not exist. The few-shot memory's code is live but its vector collections were never created on this deployment. | Built, unfed |
| 6 Training engine | Nothing; no training dependency in the tree. The plan exists as MI-4 to MI-6 (ROADMAP §3.9). A fine-tune could be served today through Ollama or LM Studio only. | Absent until gates |
| 7 Environment and tools | 38 conversation tools always present and 4 conditional, 11 analyst tools, 13 registered connectors plus DuckDB, Postgres and the ops connection, a seeded samples warehouse, an MCP server with 18 fixed tools, declared actions with risk tiers and an approval inbox. No environment reset, no trajectory replay. | Live |
| 8 Agent rollout | Tool loop at 8 or 24 steps by model tier, token and time budgets, stop reasons recorded, every pick written as a decision record, a scheduled path on a 60-second heartbeat. Nothing re-executes a stored trajectory. | Live |
| 9 Verification, agentic | Environment feedback live. Completeness ratios and run status, but nothing checks that the goal was met. Departure gate on outbound sends only: 30 judged, 13 held, 0 human marks. SQL, PII, SSRF and secret safety live; no harm or jailbreak check. | Half |
| 10 Trajectory processing | 188 decision records. Outcome is `ok` on all 188, confidence is 0.0 on all 188, and the trace id joins nothing. No replay buffer, curriculum or relabeling. | Capture only, unlabeled |
| 11 Training, agentic | Nothing. JD-6's local tool-choice scorer is on hold because this corpus cannot train it. | Absent |
| Shared infrastructure | Dataset registry with content hashes and lineage. Model ids config-only over seven backends with a failover chain; no adapter registry. 14 flags with graduation receipts, the last from July; four flags defaulted on 2026-09-24 without one, at the user's call. 44 registered SQLite stores, an embedded vector store, no object store. A single-process job kernel, no GPU. Observability routes live, but all 97 of the day's model calls unpriced. Auth off locally; vault, audit feed and the custody law in place. | Mostly live, local only |
| Unified trajectory store | 17 run-level stores with no shared run id. The trace id reaches only the observability tables. Verdicts are kept forever while events sweep in 14 days. | Absent |

---

## 1 · The numbers that decide

**MI-4's entry gates**, read live from `GET /learning/datasets` on 2026-09-24:

| Gate | Have | Need |
|---|---|---|
| SFT pairs | 0 | 1,000 |
| Preference pairs | 0 | 150 |
| Golden examples | 5 | 150 |
| Days of guard data | 21 | 30 |
| Bronze rows (not a gate) | 0 datasets | — |
| Repair pairs (not a gate) | 0 datasets | — |

**The inputs that feed them**, lifetime on this instance unless stated:

| Signal | Count | Where read |
|---|---|---|
| Ask turns | 68 (19 converse, 49 fast path; 2 converse turns stopped on budget) | `GET /obs/route-mix` |
| Human verdicts | 5 (2 accept, 1 correct, 2 reject), none with SQL | `data/verdicts.db`, `GET /learning/summary` |
| Chat feedback events | 0 (`chat.feedback`), 1 (`trace.feedback`) | `session_events` |
| Treatment-shadow rows | 3 in the first day (2026-09-23 19:54 to 2026-09-24 09:06) | `session_events` kind `treatment_shadow` |
| Decision records | 188 (analyst 120, converse 68); outcome `ok` 188 of 188; confidence above 0 on 0 | `data/decisions.db` |
| Trusted queries | 12 entries, 1 with a verifier | `data/trusted_queries.json` |
| Model calls, 24 h to 2026-09-24 20:25Z | 97 calls, 266,150 tokens, 97 unpriced, cache hit 0.259, 2 failures | `GET /obs/usage-summary` |

The bound model that day was `deepseek/deepseek-v4.1-flash` on openrouter for every role; the fallback link is
`z-ai/glm-5.3-flash:free`. The largest call sites by tokens were the explorer agent, the tool loop, and
`sql.writer:fix` (19 calls to 4 for `sql.writer:write`).

**The company-brain map for theLook** (`GET /brain/map?connection_id=8233e4fd`): 280 dated facts, 110 findings in the
graph, 2 approved metrics of 7, 30 messages judged at the departure gate with 13 held, 0 recommendations with an
outcome, 0 claims checked, 0 of 1 named owners reachable.

---

## 2 · Box 1 — where problems come from

**Task datasets are offline files plus a live evals plane.**

- `evals/golden_sql_expanded.jsonl`: 53 questions, each with `reference_sql`, expected columns, a difficulty (25 easy,
  22 medium, 6 hard) and a category; target `samples`. All 53 are replayed by `tests/integration/test_golden_reference.py`.
- `evals/ablation_*.jsonl`: 86 questions with `reference_sql`, pitfall and trap — LuxExperience `914df862` 32, Olist
  `baef6c3e` 19, `samples` 12, missimi on `workspace` 23 (its schema no longer exists; the harness skips it).
- Other labelled files: `evals/framing_matcher_set.jsonl` 77 (lux 47, olist 30; dev 42, test 35),
  `evals/object_query_coverage.jsonl` 26 (a person wrote the object query; 22 compile), `evals/authoring_asks.jsonl` 30.
- Pack goldens carry an expected value with a tolerance and no SQL: banking 51 (FDIC 2025-Q2), airline 14 (BTS
  2019-01), customer analytics 2.
- Spider2-Lite: 135 local tasks; the dataset lives outside the repo (`evals/spider2.py:59`, `SPIDER2_ROOT`, absent
  here). The July run scored 72 of 135 by the official script (`docs/10X_AND_SPIDER2_PROGRAM_2026-07-06.md:315`).
- `data/evals.db`: 11 suites, 197 cases, 36 runs, 751 results. Correctness-labelled: Superstore `8d36d4c2` (24 cases
  with reference SQL) and `nl2sql-golden-v2` (5). Consistency-only, built from receipts with the headline as the
  expectation: 22 and 102 cases on `workspace` (`aughor/evals/from_receipts.py:13` says so).
- `evals/semops_band_gold_thelook_800.json`: 800 rows by 6 predicates; the file says these are model labels, not human.
- `evals/README.md:190-240` documents `evals/golden.jsonl` and `evals/run.py`; neither exists.

**Internal context is live in prompt assembly; its vector-indexed parts are empty here.** `data/ontology_docs` 1,286
files; `data/ontology_overrides` 61; column config 104; `data/shipped` 25 declaration files (LuxExperience 18, Olist 3,
samples 2, theLook 2); `glossary_generated.yaml` 264 tables; `metrics.json` 4 plus `metrics.instance.json` 8;
`global_rules.md` 211 lines; `documents.json` 18; ambiguity resolutions 7. The packs' knowledge bases hold 63 files and
282 hand-written patterns, 270 with a SQL template, and the Qdrant collection `sql_knowledge_base` has 0 points.

**Synthetic problem generation is absent as a source of training or eval data.**

- `aughor/evals/perturb.py:56`: surface-only rewrites (case, punctuation, whitespace, a courtesy wrapper); paraphrase
  models excluded on purpose (`:15-20`); opt-in via `aughor/evals/runner.py:168-225`.
- `aughor/ontology/doctree.py:227`: three template questions per table, used only as starter chips
  (`aughor/starters.py:94`), no answers attached.
- `aughor/business_profile/infer.py:474`: the model writes SQL for the key questions it wrote; 33 questions and 30 SQL
  in `data/business_profile_*.json`; nothing exports them.
- `aughor/evals/from_receipts.py:146`: receipts become consistency cases; only tests call it.

**Human-written examples.** `data/trusted_queries.json` 12 entries — 11 grandfathered on `workspace` with no status and
no verifier, 1 approved with a verifier on `8233e4fd` — injected into prompts on live paths (`aughor/tools/grounding.py:130`,
`aughor/routers/investigations.py:2173`, `aughor/feedback/priors.py:152`). `data/agents.db` `user_agent_goldens`: 5 rows
with reference SQL (theLook). `data/verdicts.db` `finding_verdicts`: 5 rows, none with `sql_source` or `corrected_sql`,
so there is no human-corrected SQL anywhere.

**Human-labelled question-to-SQL pairs per connection**, about 168 in all:

| Connection | Pairs | Source |
|---|---|---|
| samples | 65 | golden 53 (11 with alternatives) + ablation 12 |
| LuxExperience `914df862` | 32 | ablation |
| workspace | 23 | ablation (missimi, schema gone) + 11 legacy trusted queries + 2 trusted programs |
| Olist `baef6c3e` | 19 | ablation |
| Superstore `8d36d4c2` | 24 | evals suite |
| theLook `8233e4fd` | 5 | agent goldens, plus 1 approved trusted query |

---

## 3 · Boxes 2 and 8 — how a trajectory is produced, and how many per problem

**The loop.** `run_tool_loop` (`aughor/agent/tool_loop.py:107-265`) makes one tool call per step; bad arguments,
unknown tools and tool exceptions are fed back to the model rather than raised (`:181-238`); every pick with a menu of
two or more is written as a decision record (`:244-254`). Step budgets come from the model profile: 4 converse and 10
analyst steps at the baseline tier, 8 and 24 for a model declaring 128k or more of context
(`aughor/llm/profile.py:113-173`; env `AUGHOR_TOOL_LOOP_STEPS`, `AUGHOR_DEEP_LOOP_STEPS`). The loop ends `answered`,
`budget` or `silent` (`tool_loop.py:70-75,191,203,265`). Per-agent run budgets — Explorer 200k tokens and 600 s, Analyst
500k and 900 s (`aughor/kernel/agents.py:107-169`) — are enforced by the heartbeat (`aughor/kernel/jobs.py:359-395`);
79 `budget.exceeded` events live. The explorer's own hard cap is 15 (`aughor/explorer/agent.py:2303`).

**The model call.** `complete_with_tools` (`aughor/llm/provider.py:2072-2215`): temperature 0.1 by default,
`tool_choice="auto"`, max tokens capped per role, the fallback chain on failure (`:2143-2168`). Binding order: org
overlay (`org_llm.db`, 0 rows), then `data/llm_config.json`, then env (`:627-806`). Only one call site ships tool
schemas (`:2078`). Anthropic receives a temperature only when a run pins one (`:2188-2196`).

**Fast path versus converse.** `ask.converse` is on by default (`aughor/kernel/flags.py:263-270`) and requires a model
that can call tools (`aughor/agent/converse_tools.py:783-828`). The branch is at `aughor/routers/investigations.py:5424-5520`;
`fast_path_turns` is the residual `total - converse` (`aughor/obs/session_log.py:617`). Stale docstrings still say
converse is off by default (`aughor/routers/obs.py:516`, `session_log.py:525`, `flags.py:341`) and that tool calls are
"NOT YET EXERCISED AGAINST A LIVE BACKEND" (`provider.py:2107`).

**The scheduled path.** `tick_once` every 60 s (`aughor/automations/scheduler.py:33-120,220-235`) covers automations,
monitors, briefs, agent alerts, parked runs, settling checks and answer re-checks; investigations run via
`aughor/runners/investigation.py:238`. Scheduled monitor ticks make no model calls of their own; a scheduled
investigate becomes one of the deep traces.

**More than one trajectory per problem — nothing on the live path.**

1. Treatment shadow (`aughor/judgment/treatment.py:169-209`): one extra model call after the answer, predicting the
   treatment; stores prediction, what ran, and `agreed`; never a second trajectory. Off by default in code
   (`flags.py:93`), on through `.env` on this deployment; 3 rows.
2. `sql_consensus.generate_consensus_sql` (`aughor/agent/sql_consensus.py:100`): k samples, execute, vote. Zero
   callers.
3. Spider2 strategy candidates (`evals/spider2_candidates.py:107-139`, `evals/spider2.py:444-475`): eval-only; keeps
   each candidate's strategy, ok and result signature, only the winner's SQL.
4. Ambiguity probe (`aughor/agent/ambiguity_probe.py:118-146`, env `AUGHOR_AMBIGUITY_CLARIFY`): up to three readings;
   all labels kept, only the winning SQL (`aughor/semantic/ambiguity_ledger.py:102-118`).
5. Eval iterations (`aughor/evals/store.py:98-110`): pass and score per iteration, no answer, no trajectory; 3 of 36
   runs used 3 iterations.
6. Experiment grid and A/B (`aughor/evals/experiments.py:62-80`, `compare.py`): per-case outcomes for every arm.
7. Model bake-off (`evals/model_bakeoff.py:207-227`): per-model totals (glm-5.2 0.630, kimi-k2.7 0.633,
   minimax-m2.5 0.631 execution accuracy on the 53).
8. Ablation eval (`evals/ablation_eval.py`): every arm's SQL and verdict per question.
9. Replay controls (`evals/jev_shuffled_control.py`, `evals/judgment_battery_eval.py`): decisions re-asked with swapped
   context; JSON output.
10. Retries and failover (`provider.py:1548-1595`): only a `retries` count (23 rows) and a `fallback` flag (10 rows);
    the failed attempts are not stored.

**Replay.** Replay-argument capture runs only inside an operator's prompt-capture window (`tool_loop.py:258-260,289-337`;
`session_log.py:191-228`), off by default, consumed only by an offline eval that reports inconclusive
(`evals/judgment_battery_eval.py:375`). Stored answer SQL is re-executed daily and on demand
(`investigations.py:6149`). Interrupted investigations are salvaged from the LangGraph checkpoint (`investigations.py:753`).
Nothing re-executes a stored agent trajectory.

---

## 4 · Boxes 3 and 10 — what a run record holds, and where

**Facts that apply to every store.** Logprobs are stored nowhere; no provider call asks for them
(`aughor/judgment/seam.py:17-18`). The only sampling parameter recorded is temperature (1,726 of 1,744 model-call rows);
no max_tokens, top_p or seed. Prompts and responses are kept only while an operator's capture window is open
(`aughor/obs/session_log.py:154-188`; default 20 calls or 15 minutes): 3 of 1,744 calls. Cost is token and time
counters; dollars are computed at read (`session_log.py:383-388`). The model id on answer receipts is null on 1,276 of
1,277 chat and deep receipts, because `aughor/routers/investigations.py:346` reads `get_provider("coder").model` and
`LLMProvider` has `_model` and no `.model` property (`aughor/llm/provider.py:2030`).

**The stores.** Missing column: P prompt, M model, Tk tokens, S steps, R reward.

| # | Store | Captures | Missing | Written | Live rows |
|---|---|---|---|---|---|
| 1 | `session_events`, `data/system.db` (`aughor/kernel/ledger.py:231-283,456-462,494`) | model calls (model, provider, tokens, temperature, role, caller, retries, fallback, ms, ok); tool entry and exit (name, ok, span, SQL input); question; final response (receipt id, headline); `treatment_shadow` | P (window only), tool args and results, step index, R | always (`session_log.py:77-84`); trace-less events dropped (`:270-272`); 14-day sweep unless pinned (`:742-777`) | 6,806 (tool results 1,914; model calls 1,744; tool calls 1,575; guardrail 1,394; questions 72; final responses 70) |
| 2 | `task_history`, system.db (`ledger.py:193-206`) | one row per span: input SQL, output, start, end, error | M, Tk, P, R, answer | always (`aughor/telemetry.py:561-565`), never pruned | 33,126 |
| 3 | `events`, system.db (`ledger.py:112-120`) | lifecycle kinds; free-form JSON | nearly everything | always; only job and automation chatter pruned | 73,712 |
| 4 | `jobs`, system.db (`ledger.py:148-163`) | run state, attempt, timestamps, token and time counters | P, M, S, answer, R | every kernel job | 130,024 (492 investigations) |
| 5 | Trust Receipt `artifacts` + `lineage`, system.db (`ledger.py:126-146,831-871`) | question, headline, first SQL, tables, cost, model (null), agent; lineage of SQL, inputs, guards, metrics | M (bug), P, params, S, R | every answer | 37,699 / 83,600 |
| 6 | `investigations`, `data/history.db` (`aughor/db/history.py:167-185`) | question, status, error, report, hypotheses, per-query history | M, Tk, P, R; per-query history empty on all 69 September deep runs | every turn | 1,113 (825 chat, 288 investigation) |
| 7 | LangGraph checkpoints, `data/checkpoints.db` (`aughor/agent/graph.py:56-87`) | full graph state per node | M, Tk, P, R; exists to resume | older deep-graph path | 1,823 checkpoints, 15,476 writes, 245 runs |
| 8 | `audit_log` + `guard_verdicts`, `data/audit.db` (`aughor/security/audit.py:50-92`) | every SQL run (full SQL, verdict, rows, ms, error); guard fires | everything about the model | every execution, append-only | 62,753 / 337 |
| 9 | `decision_record`, `data/decisions.db` (`aughor/learning/decisions.py:71-90`) | per pick: menu, choice, ok or error, short context, prompt hash | args, results, M, Tk, human labels | each loop step with a menu of 2 or more | 188 |
| 10 | Explorer step log, `data/episodes_*.jsonl` (`aughor/explorer/episodes.py:37-60`) | per step: think, sql, observation | M, Tk, params, R, trace id | every explorer step | 2,408 lines |
| 11 | `automation_runs`, `data/automations.db` (`aughor/automations/store.py:69-90`) | outcome, conditions fired, effects | M, Tk, P, S | every tick | 76,780 (551 fired) |
| 12 | eval harness, `data/evals.db` (`aughor/evals/store.py:84-126`) | run config (model per role, flags, temperature); per case and iteration pass, correct, scores; graduations | P, S, Tk | each eval run | 36 runs, 751 results, 9 graduations |
| 13 | `evidence_claims`, `data/evidence_ledger.db` | claim, SQL, confidence, owner feedback | M, Tk, P | deep runs | 1,503 |
| 14 | `finding_verdicts`, `data/verdicts.db` | accept, correct, reject, the SQL that ran, a corrected SQL | the rest | on click | 5 |
| 15 | `departures`, `data/departures.db` | gate decision per outbound message, a verdict | M, Tk, P | per departure | 30 |
| 16 | `staged_proposals`, `data/kinetic_inbox.db` | proposed action, reasoning, outcome | M, Tk | per proposal | 13 |
| 17 | offline eval files, `evals/*.json(l)`, `evals/spider2_out/traces/`, `evals/bakeoff_out/` | per-arm SQL, class, match; Spider2 per-step lists; bake-off totals | no common schema | per script run | 135 Spider2 traces, 2 MLflow runs |

Minor: ledger key-value entries `agent_runs` (221) and `action_logs` (336), `eval_baseline.db` (5 runs, 265 items),
`ambiguity_ledger.db` (7), `learning.db` (4 dataset nodes). Empty: `quality_results` 0 rows; `investigations.db`,
`kernel.db`, `exploration_state.db` zero-byte files. The MLflow and OTLP exporters are off (commented out in `.env`).

**The five audit sinks** named in `aughor/govern/audit_categories.py:6-10` are now merged by a read-only `feed()` over
three physical tables; it still leaves out `guard_verdicts` and four governance-shaped kinds (`:127-129`). Audit has one
merged view; run records do not.

**Join keys, with live coverage.**

- `trace_id` is meant to be the spine and connects only the observability tables: of 475 traces in `session_events`,
  435 also appear in `task_history` and 403 in `audit_log`; `session_events` and `task_history` also share `span_id`
  (`telemetry.py:626-719`).
- Deep runs use the investigation id as the trace id (`aughor/routers/obs.py:177-183`); live, 9 model-call traces
  match an investigation id, and 48 of 1,113 history rows still have events after the sweep.
- Working links: the final response's `receipt_id` resolves for 28 of 70 rows; `job_id` is set on 1,632 of 1,744
  model calls; the `investigation.dispatched` event records job, investigation, receipt and agent
  (`aughor/runners/investigation.py:211-235`).
- Broken or empty: `decision_record.trace_id` is a fresh uuid per turn (`investigations.py:3528`) and matches nothing;
  its only link is `inv_id` via `attach_run` (`decisions.py:294-324`), set on 130 of 188 rows, 123 resolving.
  `automation_runs.trace_id` is the run's own id (`aughor/automations/engine.py:2026`); of 360 fired runs since
  2026-09-10, 49 appear in `events` and none in the other three. `history.trace_id` was added on 2026-09-24
  (`history.py:145-152`) and is empty on all 1,113 rows. `eval_runs.trace_id` is empty on all 36 runs. Answer receipts
  never set `created_by_job`. `staged_proposals.run_id` joins nothing. The explorer's step log has only an episode id.

**The agent step record exists only in memory.** `run_tool_loop` builds `LoopStep{tool, arguments, ok, detail,
result_chars, prompt_chars}` (`tool_loop.py:50-75`) and returns them in a `LoopResult`; none of it is saved. What is
persisted per step: a `tool_call_result` event with the tool name, `ok` and `{body, detail}` (`investigations.py:3488-3490`
converse, `:3711` analyst), where `detail` is empty on success (`tool_loop.py:236`); a decision record under its own
trace id; one summary per turn with the tool names, `stop_reason` and `injected_chars` (`investigations.py:3637-3644`,
`:3773`); model-call rows with no step index; nested SQL spans. Arguments appear only in the live SSE `converse_step`
frame, truncated to 400 characters (`investigations.py:3477-3484`); tool results and the model's text between calls are
never stored. No route returns (tool, args, result, model output) per step; `GET /traces/{trace_id}` returns ordered
events and the span tree (`obs.py:211-300`).

**Retention conflicts.** `session_events` sweeps at 14 days unless a verdict pins (`pinned_at`, MI-2); `events` prunes
only `job.state` and `automation.run` (MI-2a); `task_history`, `audit_log`, verdicts and claims are unbounded. A late
verdict's evidence is gone unless it pinned in time.

---

## 5 · Boxes 4 and 9 — verification and reward

Tags: **[C]** code exists, **[L]** wired live, **[D]** data populated.

**(a) Exact answer verification — eval only.** The golden scorer (`evals/sql_accuracy.py:150` `score_single`, `:78`
`compare_result_sets`, weights `:133-143`) checks column count and names, row count, normalised row-set overlap, top-5
rows and whether the query ran, accepts alternative references, and yields `overall` in [0, 1]. It executes through
`_safe_exec` (`:22`) on the raw DuckDB cursor, skipping the connection's validation, safety check, PII redaction and
audit log. Persisted to JSON and, via the ratchet, to `data/eval_baseline.db` `run_items` (265 rows, 5 runs, all on
`samples`, July). [C][D] The product eval plane's `reference_checker` (`aughor/evals/targets.py:155`) calls
`aughor/custom_agents/quality.py:138` `results_match`, a boolean that ignores row order and tolerates extra columns —
a different judgement from the golden scorer. The runner (`aughor/evals/runner.py:541`) writes `eval_run_results` (751
rows, `correct` known on 181). `targets.py:83` `ask_target` drives the real `/ask` in-process via `build_ask_stream`.
Agent goldens (`quality.py:220`) write `user_agents.last_eval` (theLook 5 of 5). **Live: nothing compares an answer to a
known answer.** `evals/run_golden.py:46` is an unused duplicate `_safe_exec` without the date-function fix, and
`run_golden.py:116` is a hand mirror of the old `_stream_chat` SQL core that says "keep in sync".

**(b) Executable tests — live.** `SqlWriter.fix` (`aughor/sql/writer.py:509`): three code-only repairs, each accepted
only if a dry run passes (`:541-579`), then up to `max_retries` model attempts under the same rule (`:616`, `:625`);
output `FixResult(ok, attempts, error_class)`; live on the quick path at `investigations.py:2701`, a repair adopted only
once the check that asked for it stops firing (`:2705-2719`); also `aughor/sql/executor.py:197`; mirrored in the harness.
Preflight repair at `investigations.py:2641`, 304 of the 337 `guard_verdicts` rows. Alert backtest and fire drill
(`aughor/monitors/backtest.py:143`, `aughor/monitors/drill.py:113`) on demand. Exact-equivalence suite
(`aughor/evals/equivalence.py`): 9 cases, one run.

**(c) Constraint checking — live.** Read-only and SQL safety (`aughor/db/connection.py:698`, `aughor/security/safety.py:87`,
applied at `connection.py:85-120`, fail closed): `audit_log` 62,753 rows, 843 blocked, 994 suspicious; queries labelled
`__eval__` or `__departure__` skip it (`connection.py:69`). The guard battery is registered as evaluators
(`aughor/evals/builtins.py:71`): read-only and disallowed-function checks block, about twenty fan-out, lint and
capability checks warn; live through inline calls and the trust plane (`aughor/trust/__init__.py:45`,
`sql/executor.py:236`); persisted per fire in `guard_verdicts` (trace id, first 120 characters of SQL, pattern, phase,
detail): 337 rows, 330 traced. Only two producers write there (`aughor/sql/trust_checks.py:243`,
`aughor/kernel/registries/execution_hooks.py:109`). Budgets: the row cap (`aughor/security/sandbox.py`), token and time
(`aughor/kernel/metering.py:290,333`), per-agent guardrails writing `guardrail` events (1,394 rows, all PII allows,
none blocked; `aughor/govern/guardrails.py:157`), org and user caps (`aughor/govern/usage_caps.py`), a cap check before
any outbound call (`aughor/govern/outbound.py`). The departure gate (`aughor/govern/departure.py:249`): nine laws — trust
banner, caveat, tie-out, approved definition, re-measure (`_remeasure :651`, `departure_basis.py:404`), freshness, causal
licence (`_claims :769`), owner disagreement, repeat and probation; output departed, held, held_probation or held_owner
plus an outcome per law; `data/departures.db` 30 rows, 17 departed, 13 held; outbound sends only; a person may mark a
verdict (`aughor/routers/departures.py:99`, feeding probation precision at `departure_store.py:244`), 0 marked; no door
releases a held message. `GraduationDecision` (`aughor/evals/promotion.py:28`) is a yes or no with reasons in
`eval_graduations` (9 rows, last 2026-07-31); a person flips the default.

**(d) Model judges — none for answer quality.** The skeptic refuter (`aughor/agent/explore.py:1541`) halves
`earned_confidence` on the explore path (`:1692`) and caps HIGH to MEDIUM on deep runs (`investigate.py:10247`, `:9776`).
The hypothesis evidence grader (`aughor/agent/nodes.py:1023`) stores a model confidence per hypothesis on 4 of 1,113
runs. The treatment shadow judges the question, not the answer; `aughor/judgment/calibration.py:130` computes a
calibration error for two levers only. Jev (`aughor/judgment/jev.py`) judges data-row predicates. `evals/mlflow_scorers.py:1`
and `quality.py:12` both say "no LLM judges"; LLM-judge over live traffic was dropped on 2026-09-06.

**(e) Human feedback — code live, data near empty.** `aughor/feedback/verdicts.py:66`: accept, correct, reject, the SQL
that ran, an optional corrected SQL, keyed by investigation id. Doors: `aughor/routers/verify.py:37`; the chat's 👍
(`aughor/routers/query.py:1087`, records an accept carrying the SQL the turn ran); forwards from departure verdicts. Side
effects: reject or correct marks the run's decisions (`aughor/learning/decisions.py:258`), updates the ambiguity ledger,
evicts the answer from the few-shot memory; past verdicts are read into prompts (`aughor/feedback/priors.py`). Data: 5
verdicts, none with SQL; 0 `chat.feedback` events; 1 `trace.feedback`. Other human stores: approval inbox 13 proposals
(2 executed, 6 rejected, 4 superseded, 1 pending); `evidence_claims.owner_feedback` 2 of 1,503; ambiguity resolutions 7;
pack deltas awaiting accept 0. The MI-4 gate (`aughor/learning/exporters.py:539`) counts only human-graded kinds;
execution-graded rows (`:423`) and guard rewrites (`:453`) are reported as "not a gate".

**(f) Rewards.** Outcome level: `earned_confidence` in [0, 1] on 5 of 1,113 runs (`report_json.verification`), explore
mode only, measuring guard coverage times completeness times data trust, not correctness; deep-analysis `confidence`
HIGH, MEDIUM or LOW on 223 reports, stated by the model and only capped by code. Process level: guard coverage in the
verification manifest (`explore.py:1561`), `plan_reconciliation` (`aughor/agent/orchestrator.py:163`) and contradiction
severity (`:271`) on 223 rows, `is_compoundable` (`aughor/feedback/gate.py:20`). Step level: `decision_record`
(`tool_loop.py:247`), 188 rows, outcome `ok` on all, confidence 0.0 on all, none labelled by a person;
`evidence_claims.confidence` is a fixed heuristic, 0.8 if significant else 0.5 (`aughor/evidence/linker.py:117`). **No
reward function and no training loop.** The 825 chat turns carry no score; receipts carry cost and tokens only.

**(g) Task success on multi-step runs.** Explore: completeness as sub-questions answered over planned
(`explore.py:1680-1687`) and a forced disclosure of failed steps (`:1706`). Deep analysis: skipped and unplanned phases in
the plan reconciliation; run status in `history.db` 232 complete, 40 failed, 9 timed out, 7 paused. Conversation: stop
reason and step count to the session log (`investigations.py:3636`). **Nothing checks that the final answer achieved the
goal.**

**(h) Environment feedback — live.** SQL error and dry-run text into the repair loop; zero-row diagnosis
(`sql/executor.py:31`); tool exceptions returned to the model (`tool_loop.py:226-233`); `tool_call_result` rows with `ok`
(1,914, 7 failed); `task_history` spans 33,126 with 28 errors. Answer re-check (`aughor/answer/recheck.py:296`) re-runs an
answer's own query daily: changed, unchanged or unchecked, appended to `report_json.rechecks` (10 entries); consistency
over time, not truth; flag on by default.

**(i) Safety.** Live: SQL safety and read-only; PII scan and redaction on every result (`aughor/security/pii.py:93`);
prompt-injection fencing of warehouse text (`aughor/util/prompt_safety.py:56`, mitigation only); SSRF check on webhook
URLs (`aughor/util/url_guard.py:27`); secrets encrypted at rest (`aughor/secretvault.py`; `PENDING.md` notes a possible
wrong-key defect, unverified). Eval-only: robustness to meaning-preserving rewording (`aughor/evals/perturb.py`). Absent:
harm, toxicity or jailbreak detection; red-team runs are listed as owed.

**Two corrections to standing prose found here.** "The grounded-answer guard is persisted per fire" is not so: the
quick path's receipts (`investigations.py:1644`) and the conversation agent's number-grounding receipt (`:3585`) reach
only the stored answer envelope (`aughor/answer/envelope.py:264`, `investigations.py:5563`, since 2026-09-23), never
`guard_verdicts`; 4 envelopes are stored and the 3 chat ones hold 0 receipts. And the `phase` column in `guard_verdicts`
means two things — the execution phase on E1 rows and the action on rewrite rows — so the eval-versus-live filter
(`aughor/security/audit.py:354`, `phase != 'eval'`) works only on E1 rows, and the quick path labels its E1 fires
`phase="deep"` (`investigations.py:2834`).

---

## 6 · Box 5 — selection and transformation

**What #547 built** (ROADMAP §3.42, §3.43): the exporters reworked (`aughor/learning/exporters.py`), the chat's 👍 as
an accept (`aughor/routers/query.py:1087`), quick answers remembered (`aughor/routers/investigations.py:5572`).

**Exporters — built, manual, and the data is about empty.** `export_sft` (`exporters.py:272`): accepts whose SQL ran,
plus trusted queries with a verifier (tiers silver and gold). `export_dpo` (`:298`): corrections whose corrected SQL
dry-runs (`:259`). `export_golden` (`:326`): a tenth held out by question hash (`:78`). `export_bronze` (`:423`): kind
`sft_bronze`, graded by execution. `export_repair_pairs` (`:453`): kind `dpo_repair`, guard rewrites as before and
after. `export_decisions` (`:493`). Transforms: sha256 dedupe (`:117`), a PII scrub that drops the text when scrubbing
fails (`:38`), reconciliation to each answer's latest verdict (`:170`), org scope (`:244`), context of connection,
dialect and tables (`:227`), a split that keeps golden questions and their SQL out of training (`:86-114`). Gates at
`gate_status` (`:539`). The only trigger is `POST /learning/export` or `/learning/export/decisions`
(`aughor/routers/learning.py:174`, `:154`); scheduling is deliberately absent (`:91`).

`data/learning.db`: `nl2sql-sft` v1 0 rows, `nl2sql-dpo` v1 0, `nl2sql-golden` v1 0 (all 2026-09-03), `nl2sql-golden`
v2 5 rows (2026-09-06, lineage 5 `agent_golden`). No `sft_bronze`, `dpo_repair` or `choice` dataset exists: nothing has
been exported since #547. The blobs point to `data/datasets/*.jsonl` and that directory does not exist, so
`store.rows_of` returns an empty list. Material available today: `history.db` holds 821 completed chat turns and 232
completed deep analyses, none with a trace id; 3 chat rows carry an envelope and none a rewrite receipt, so bronze
would yield at most 3 rows and repair pairs 0.

**Few-shot memory — code live, store empty.** `aughor/tools/prior_analyses.py`: collections `aughor_sql_examples` and
`aughor_investigations` (`:30-31`); writes `index_sql_examples` (`:285`: no error, at least one row, no caveats, not
overruled) and `index_answer` (`:357`); reads `_search_sql_examples` (`:415`), top 3 at score 0.70 or better (`:281`).
Wired: writes at `aughor/agent/bootstrap.py:120-131` and `investigations.py:5565`; reads at `investigations.py:1761`,
`aughor/agent/nodes.py:692-694`, `aughor/tools/grounding.py:151-156`; tombstone on reject or correct at
`aughor/feedback/verdicts.py:112-119`, `:156`. Data: the embedded store's `data/qdrant/meta.json` lists
`schema_suggestions`, `sql_knowledge_base` and `aughor_schema`, all with 0 points; neither few-shot collection exists;
`.env` sets no `AUGHOR_QDRANT_URL`, `AUGHOR_DB_URL` or `AUGHOR_EMBED_BACKEND`.

**Decision records — captured, not trainable.** `aughor/learning/decisions.py:71-90`, written from `tool_loop.py:247`,
`aughor/agent/nodes.py:185`, `aughor/agent/framing.py:125`. 188 rows: `analyst.tool` 120, `converse.tool` 68 (10
attributable to a connection); 0 rows for `ask.route` or `framing.definition`. The writer records
`outcome="ok" if ok else "error"` where `ok` means the tool did not raise (`tool_loop.py:251`); `mark_outcome` is driven
only from reject and correct verdicts (`decisions.py:258`), so on a mostly-correct system the label is constant.
`corpus_yield` (`:327`) reports it as non-discriminating.

**Other selection mechanisms.** Best-of-K by execution-signature plurality only in the Spider2 harness
(`evals/spider2_candidates.py`). `aughor/agent/sql_consensus.py`: no importer. `aughor/evals/promote_trusted.py:46,74`:
no caller. Pack flywheel (`aughor/packs/flywheel.py:35,69`, called at `aughor/agent/explore.py:1891-1905`):
`data/pack_deltas.db` 0 rows. Difficulty filtering and curriculum: absent; difficulty is used only in eval reporting
(`evals/run_golden.py:668`).

---

## 7 · Boxes 6 and 11 — training

**Code: absent.** No torch, transformers, peft, trl, unsloth or deepspeed import or dependency; `pyproject.toml` extras
are evals (braintrust) and observability (mlflow-skinny, langfuse). "Checkpoint" in this repo is the LangGraph
checkpointer; "distill" is prompt-level pack deltas. Grep over `aughor/` for reinforcement, rlhf, behaviour cloning, PPO,
GRPO, lora: zero hits that are not a demo string or a comment.

**Plan: ROADMAP §3.9.** MI-4 (`ROADMAP.md:2468-2489`): LoRA SFT then DPO, rented, adapters as `model_adapter`
artifacts, served as one more OpenAI-compatible binding, routed micro-first with escalation on a guard fire; MI-5 the
deployment posture; MI-6 GRPO after a measured plateau, with a binary deterministic reward audited by hand first.

**Model backends** (`aughor/llm/provider.py:60-61`): ollama, lmstudio, groq, together, anthropic, gemini, openrouter,
plus a test-only faux. No direct OpenAI, Bedrock or Vertex backend. Model ids are free-form per role (coder, narrator,
fast) with no default (`:89`); resolution order org overlay, `data/llm_config.json`, env (`:710`, `:783`). Custom ids
can be added to the picker (`aughor/llm/models.py:69`); a per-agent pin exists (`aughor/kernel/agents.py:272`,
`kernel/jobs.py:345-356`) and never applies to the fast role (`provider.py:483`). Base URL override only for ollama and
lmstudio (`:65`, `:3045-3054`; `OLLAMA_BASE_URL`, `LMSTUDIO_BASE_URL`), which send a dummy key (`:848`, `:956`); every
hosted URL is fixed (`:77-87`). An unknown id gets the most conservative prompt tier: "an unknown model is somebody's
fine-tune we know nothing about" (`aughor/llm/profile.py:108-111`). A paid OpenRouter model needs `allow_paid` (`:2939`).
Failover chain anthropic, gemini, groq, together, openrouter with a 900 s quota cooldown (`:285-351`). `_fallback_model()`
(`:279-282`) defaults to the literal `"claude-opus-4-8"`, which the no-model-id ratchet
(`tests/unit/test_llm_model_catalog.py:311`) does not see because its pattern wants a slash.

**Could a fine-tuned model be plugged in?** Yes through Ollama or LM Studio at a local URL, or any OpenAI-compatible
URL that needs no key. Likely yes as a Together-hosted fine-tune id against the fixed URL (untested). No for a rented
endpoint that requires a key. MI-4's "serve" binding is not built.

---

## 8 · Box 7 — the environment

**Tools** (`aughor/agent/converse_tools.py:564-664`): 38 always present, 4 conditional. Warehouse: `answer_question`,
`run_sql`, `list_tables`, `describe_table`, `deep_analysis` (`:597-661`). Platform reads (`aughor/agent/platform_tools.py:753-899`):
`search_graph`, `describe_entity`, `list_findings`, `get_briefing`, `get_table_health`, `list_trusted_queries`,
`list_monitors`, `list_packs`, `read_pack`, `search_documents`, `platform_help`, and `propose_context_note`, a write
that applies or stages (`:885-898`). Spotlight Know (`aughor/agent/spotlight_tools.py:649-771`): `list_platform_connections`,
`platform_usage`, `platform_limits`, `platform_runs`, `investigation_cadence`, `answer_accuracy`, `table_popularity`,
`platform_traces`, `platform_premortem`, `platform_audit`. `get_object` (`aughor/agent/object_tools.py:88`), `platform_guide`
(`aughor/agent/spotlight_guide.py:411`). Spotlight Act (`aughor/agent/spotlight_act.py:994-1109`): `set_preference`
applies at once; `draft_agent`, `draft_automation`, `edit_automation`, `draft_monitor`, `draft_brief`,
`pause_or_resume_automation`, `set_agent_limit`, `propose_agent_grant` stage a proposal. Conditional: `propose_action`
(only with `tool_grants`; stages, never executes; `aughor/agent/action_tools.py:38-137`), `present` (streaming only),
`delegate_task` (other agents exist), `query_objects` (behind `ask.query_objects`, off and parked). The comment at
`aughor/agent/platform_tools.py:26` still calls the roster reads-only; it is not. Analyst roster, 11 tools
(`aughor/agent/analyst.py:633-772`): `baseline`, `decompose`, `cross_section`, `premise_check`, `z_score`,
`value_lookup`, `profile_column`, `run_sql`, `list_tables`, `describe_table`, `propose_context_note`.

**Connectors.** Built in: `DuckDBConnection`, `AughorOpsConnection`, `PostgresConnection` (`aughor/db/connection.py:1073,1312,1509`).
Registered (`aughor/connectors/registry.py:309-324`): bigquery, snowflake, mysql, motherduck, exasol, local_upload, s3,
sqlite, federated, stripe, hubspot, salesforce, gsheets. Confluence and Notion are knowledge sources outside the
registry. Registered connections here (`data/connections.db`): Superstore, DuckDB, LuxExperience and its draft (duckdb),
BigQuery and theLook (bigquery), spotify (gsheets). Test files per connector range from 15 (local_upload) to 1
(hubspot, salesforce).

**A staged environment — partial.** The samples warehouse (builtin `samples`, `aughor/db/registry.py:39`,
`data/samples.duckdb`) is seeded with `ecommerce.{customers, products, orders, order_items, reviews}` when the schema is
missing (`aughor/demo/setup.py:33-37,89-118`); `data/aughor.duckdb` holds an outage scenario; `data/luxexperience_demo.duckdb`
and `data/superstore.duckdb` are local. theLook is a BigQuery connection (`8233e4fd`); ROADMAP §1's "mirrored daily
07:00" was not found in connector code by this census and is unverified. Reset is absent as a general mechanism (only
`POST /exploration/{conn_id}/reset`, `aughor/routers/exploration.py:1119`). Snapshot exists: freeze an artifact
(`aughor/kernel/freeze.py`, `aughor/routers/lifecycle.py:133-182`), pin a data version (`aughor/db/snapshot.py:95,115`);
exact replay only on DuckLake, plain DuckDB can only detect that data changed. The scripted faux backend
(`aughor/llm/faux.py`) serves 25 test files. `aughor/samples/` contains only `__pycache__`.

**The tool API.** `ToolSpec` is name, description, JSON-schema parameters and `run`, serialised to the OpenAI function
format (`aughor/agent/tool_loop.py:31-47`); no permission or risk attribute — guards run inside tool bodies and gating is
by whether a tool is offered. HTTP seam `GET/POST /spotlight/tools` (`aughor/routers/spotlight.py:33,54`). MCP server as
a separate process (`python -m aughor.mcp`): 18 fixed tools (`aughor/mcp/server.py:53-315`) plus automation and Spotlight
tools added dynamically (`:369`, `:406`). External MCP servers: read-only-first classification
(`aughor/mcpservers/models.py:188`), per-tool grants (`aughor/routers/mcpservers.py:205-245`), reachable from automations
only (`aughor/automations/engine.py:1603`). Declared actions carry `risk` read_only, low or high, default high, and
`parallel_safe` default False (`aughor/ontology/models.py:973-982`); the executor raises the tier for anything that spends
budget (`aughor/actions/executor.py:552-567`).

---

## 9 · The shared-infrastructure strip

- **Dataset registry and provenance — live, partial.** Datasets versioned, content-hashed, with parent lineage
  (`aughor/learning/store.py:1-80`). The context graph allows 11 source types and none is model-inferred
  (`aughor/ontology/context_graph.py:36-95`). Seed overlays: a shipped seed plus a per-install instance file
  (`aughor/semantic/metrics.py:40-81`, `data/shipped/`). `_removed_seeds.json` tombstones deleted upload seeds
  (`aughor/connectors/file/local_upload.py:72-75`). `data/metrics.json` carries uncommitted edits although
  `metrics.py:49-53` calls it frozen. `AGENTS.md` names `data/vocabulary/` as a tracked tree; no such directory is
  tracked or present.
- **Model and checkpoint management — live for bindings, absent for checkpoints.** Section 7 above. Ollama is the
  default backend when nothing is set (`provider.py:664`). Health ping (`:3072-3126`). Model change at runtime:
  `POST /llm/config` (`aughor/routers/llm.py:45`), per-agent pin via `PATCH /agents/{id}` (`aughor/routers/agents.py:90`).
  Bindings are per role, not per task. `checkpoints.db` holds LangGraph run state.
- **Experiment tracking — live.** 14 registered flags (`aughor/kernel/flags.py:24-175`), 6 on by default (`:256-302`),
  8 experiments off (`:424-565`); `RENAMED` and `RETIRED_ENV` empty. `GraduationDecision` (`aughor/evals/promotion.py:29`;
  routes `aughor/routers/evals.py:265,325`): 9 decisions, all July, none for a currently default-on flag. A/B:
  `aughor/evals/experiments.py`, `scripts/flag_ab_grid.py`. Shadow: `judgment.shadow_treatment` off in code, on through
  `.env` here. MLflow switches on only with `AUGHOR_MLFLOW_TRACKING_URI` (unset).
- **Storage — live, local.** 44 `AUGHOR_*_DB` in `tests/conftest.py` (41 SQLite, 3 DuckDB) and 27 directory or path
  variables; main ledger `data/system.db`. Postgres optional via `AUGHOR_DB_URL` (unset). Qdrant embedded at
  `AUGHOR_QDRANT_PATH` (`aughor/semantic/vector_store.py:1-30,45,108`). Object store: Blob mirroring exists
  (`aughor/control_plane/object_store.py`) and does nothing without `BLOB_READ_WRITE_TOKEN`.
- **Compute orchestration — live, single process.** One semaphore, `AUGHOR_MAX_CONCURRENT_JOBS` 8, exploration exempt
  (`aughor/kernel/jobs.py:187-243`); the 60 s heartbeat plus hourly cache eviction (`aughor/monitors/scheduler.py:89-99`);
  `/cron/tick` (`aughor/routers/cron.py:46`) exists and nothing calls it since 231f08dc and b443fc80 (docstring stale);
  in-process queue (`aughor/kernel/queue.py`); LLM concurrency capped at 4 (`aughor/llm/profile.py:332-344`). No GPU, no
  batch inference.
- **Monitoring — live, unpriced.** `/obs/*` (`aughor/routers/obs.py`): route-mix `:496`, prompt-weight `:534`,
  model-usage `:553`, timeseries `:565`, usage-summary `:603`, prompt-capture `:675-690`, agent-alerts `:812-898`,
  `/traces*` `:141-436`, `/activity` `:698,738`; `/usage` and `/audit/feed` (`aughor/routers/governance.py:22-63`);
  `/security/audit*`; `/control-room/*`. Cost: only `:free` OpenRouter models carry a hand-declared price of zero;
  everything else reads the provider's catalogue (`aughor/obs/usage.py:97-187`), and the day's 97 calls were all
  unpriced. UI: `SpendPanel`, `agentops/UsagePanel`, `TraceExplorerPanel`, `ActivityStreamPanel`, `FleetOverviewPanel`,
  `SecurityAuditPanel`, `agentops/DeparturesPanel`, `SystemPanel`.
- **Safety, governance, access — code live, main switches off locally.** `_AUTH_EXEMPT` (`aughor/api.py:226`); the API
  key (`api.py:209`) and identity requirement (`aughor/security/authz.py:45-51`) both off by default and unset in `.env`.
  Fernet vault (`aughor/secretvault.py`). Departure gate called from 6 modules. SSRF guard at `aughor/util/url_guard.py:27-47`.
  Capability gating returns 402 on a lower tier (`aughor/licensing/deps.py`) but the default tier is `enterprise`
  (`aughor/licensing/resolver.py:17-18`). Audit trail (`aughor/security/audit.py`) with a unified feed
  (`aughor/govern/audit_categories.py`). The training annex (§6 item 7) governs machine consumption of payloads.

---

## 10 · Defects found on the way (not fixed by this census)

1. Answer receipts carry a null model id on 1,276 of 1,277 rows: `aughor/routers/investigations.py:346` reads a
   `.model` property `LLMProvider` does not have (`aughor/llm/provider.py:2030`).
2. `decision_record.trace_id` is a fresh uuid per turn (`investigations.py:3528`) and joins nothing; only `inv_id`
   links it, on 130 of 188 rows.
3. `history.trace_id` (`aughor/db/history.py:145-152`) has no writer; empty on all 1,113 rows.
4. `_fallback_model()` defaults to a literal model id (`provider.py:279-282`); the ratchet at
   `tests/unit/test_llm_model_catalog.py:311` matches only ids with a slash.
5. `guard_verdicts.phase` means the execution phase on E1 rows and the action on rewrite rows; the eval filter at
   `aughor/security/audit.py:354` works on E1 rows only, and the quick path labels E1 fires `deep` (`investigations.py:2834`).
6. Grounded-answer receipts never reach `guard_verdicts`; they exist only in the 4 stored envelopes.
7. `evals/run_golden.py:46` duplicates `_safe_exec` without the date-function fix; `:116` hand-mirrors the old SQL core.
8. `evals/README.md:190-240` documents `evals/golden.jsonl` and `evals/run.py`, which do not exist.
9. `data/datasets/` is absent, so the 5 golden rows the registry lists cannot be read back.
10. The few-shot memory's collections were never created here; no embedding backend is configured, and the store's
    three collections hold 0 points.
11. `decision_record.confidence` is written as 0.0 when no probability exists (`converse.tool` never passes one), so a
    missing number reads as a stated zero.
12. Stale docstrings: `aughor/routers/obs.py:516`, `aughor/obs/session_log.py:525`, `aughor/kernel/flags.py:341`
    (converse "off by default"); `provider.py:2107` ("not yet exercised"); `aughor/routers/cron.py:3-12`;
    `aughor/agent/platform_tools.py:26` (reads-only roster).
13. `eval_runs.trace_id` empty on all 36 runs; answer receipts never set `created_by_job`.
14. `AGENTS.md` names `data/vocabulary/` as a tracked governed tree; it does not exist.
15. `aughor/samples/` holds only `__pycache__`.

---

## 11 · What the diagram's most mature phase would need here, in one list

Read against the boxes above, the mature phase is reached when all of these are true, and none is today:

1. One record per run, keyed by one id, holding steps with arguments and results, the answer, and a reward (boxes 3, 10,
   the store).
2. A label on every run that takes both values on real traffic, deterministic first, audited by hand once (box 4, box 9).
3. More than one trajectory per problem, scored against a known answer, with every candidate kept (boxes 2, 8).
4. Problems with known answers in the thousands, not the hundreds, produced without a person per row (box 1).
5. Exporters that run on a loop the platform already has, into the dataset plane that exists (box 5).
6. A student served through a binding the product already has, promoted by the graduation ratchet, routed micro-first
   with escalation on a guard fire (boxes 6, 11, MI-4 and MI-5).
7. Rewards for the agent's steps, then behaviour cloning of tool choice, then RL only after the plateau (boxes 10, 11,
   JD-6 and MI-6).

Arc TJ (ROADMAP §3.47) takes items 1 to 5 and the binding in 6. MI-4 to MI-6 stay in §3.9 and start at their gates.
