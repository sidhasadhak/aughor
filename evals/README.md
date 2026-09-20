# Aughor LLM Evals

Braintrust-based evaluation framework for Aughor investigation quality.
Separate from `tests/` — requires a live LLM and (optionally) a Braintrust account.

## What it measures

| Metric | Target | Description |
|---|---|---|
| `verdict_accuracy` | ≥ 0.80 | Agent's findings contain ≥2 expected root-cause keywords |
| `query_efficiency` | ≥ 0.90 | Verdict reached in ≤8 queries (score 1.0) or ≤12 (0.75) |
| `hallucination_rate` | 1.00 | All `key_findings` have a traceable `hypothesis_id` |

## Setup

```bash
# Install eval dependencies
uv pip install -e ".[evals]"

# Configure LLM backend (uses your existing .env)
# AUGHOR_BACKEND, AUGHOR_CODER_MODEL, AUGHOR_NARRATOR_MODEL must be set

# (Optional) Braintrust account for result tracking
export BRAINTRUST_API_KEY=...
```

## Running evals

```bash
# Smoke test — run 3 questions, print scores, no Braintrust push
uv run python evals/run.py --dry-run --limit 3

# Full dry-run — all 15 questions, no push
uv run python evals/run.py --dry-run

# Full run — push results to Braintrust project 'aughor-investigations'
uv run python evals/run.py

# CI gate — fail if any metric regresses >5% vs last Braintrust experiment
uv run python evals/run.py --fail-on-regression 0.05
```

## Intake pick validity (`intake_validity_eval.py`)

JD-2's premise, measured on historical traffic: three intake fields are picks from a set the
schema already holds — `metric_table`, `date_column`, `dimensions` — but are asked as free
text. This decodes the intake spec every deep run persisted in `data/checkpoints.db` and
checks each name against `information_schema` read out of the DuckDB warehouses themselves.

**No model call, no warehouse write**, so it is free and repeatable — and the same decode is
the AFTER measurement once a closed option list lands, so the experiment needs no new
instrument.

```bash
uv run python evals/intake_validity_eval.py --output evals/intake_validity_results.json
```

Three rules keep the number honest, each moving it DOWN: a pick naming a schema the harness
cannot read (BigQuery, or a `missimi` schema in no local warehouse) is **unverifiable**, not
invalid, and is excluded from both numerator and denominator; specs are collapsed per
`thread_id`, because a run stamps its spec into every checkpoint it takes; and comparison is
case-insensitive. `tests/unit/test_intake_validity.py` pins all three.

Status 2026-09-20 (202 investigations with a spec, 29 Jun – 19 Sep; ground truth 5 schemas,
45 tables, 350 columns):

| field | valid | invalid | unverifiable | invalid rate |
| --- | --- | --- | --- | --- |
| `metric_table` | 73 | 18 | 110 | **19.8%** |
| `date_column` | 73 | 16 | 96 | **18.0%** |
| `dimensions` | 542 | 149 | 758 | **21.6%** |

**40 of 202 runs (19.8%) proceeded on at least one name that does not exist**, and **0 of 202
threads had their spec rewritten mid-run** — so the spec-repair retry did not fix these; they
are what the investigation used. 173 of the 183 bad names are tables in no warehouse at all;
8 are a real table and column attached to the wrong schema, which cannot be schema drift.
Falsifier HOLDS.

What this does NOT measure: whether the answers were worse. Nothing grades them. The claim is
that a closed option list empties the invalid column by construction, not that accuracy moves
by a measured amount.

## Decision-corpus yield (`decision_yield_eval.py`)

The only eval here that scores the RECORD rather than an answer: of the closed-set choices
the platform made while answering, how many could a selection model ever train on? Arm A is
the corpus as the pre-A1 code wrote it, arm B is what the instrumented code writes.

**It makes no model call and opens no warehouse** — it reads a decisions store and counts, so
it is free to run and safe to run often. Arm A's three columns are structural zeros (the old
code had no parameter to carry `conn_id`, the definition chooser's response model had one
field, and the only writer of `outcome` was `tool_loop`'s inline "did it raise"), so arm A is
derived rather than re-run; paying a model to rediscover a zero is what the protocol below
exists to prevent.

```bash
uv run python evals/decision_yield_eval.py --db data/decisions.db \
    --output evals/decision_yield_results.json
```

Read a live store through a snapshot, not in place — `sqlite3 "file:data/decisions.db?mode=ro"
".backup /tmp/snap.db"`. A plain `cp` loses rows still in the WAL, and opening the live file
migrates its schema underneath a running API.

Arm A is derived PER SITE (`_ARM_A_CAPABILITY`), not as a blanket zero: `ask.route` always
passed the model's confidence, so the probability column is not what A1 bought there. An
unknown site is assumed arm-A-capable, which makes A1 look like it bought less rather than
more.

Status 2026-09-19, pre-A1 baseline (live store, 40 rows): `converse.tool` 40 rows, 0
attributable, 0 with a probability, outcomes `{ok: 40}`; `ask.route` and `framing.definition`
silent. Falsifier FIRES, as it must on rows the old code wrote.

Status 2026-09-19, arm B (8 LuxExperience questions through the instrumented router,
gemini-3.1-flash-lite, hermetic scratch store): `ask.route` 8 rows, attributable 0 -> 8,
with a probability 8 -> 8, discriminating False -> True on `{rejected: 1, corrected: 1}`
after two stand-in verdicts. Falsifier HOLDS. Caveat worth more than the pass: the model
returned confidence **1.00 on all 8**, including the question both models in the ON-10
receipts got wrong — so the probability column is populated but flat, and A2 has an input
that cannot yet rank anything.

Status 2026-09-20, arm B on the conversational path (2 real LuxExperience turns through
`converse`, same model, hermetic scratch store): `converse.tool` 5 rows, attributable
0 -> 5, with a probability 0 -> 0 (the loop passes none, by design), outcomes `{ok: 5}`
after two truthful `accept` verdicts. Falsifier HOLDS on attribution alone. Two properties
worth stating rather than discovering later: `accept` does not propagate, so a correct
answer leaves no per-pick signal; and the negative class therefore only ever arrives from
failures, which on a mostly-correct system makes this corpus heavily imbalanced.

## P7 model bake-off (`model_bakeoff.py`)

Compare candidate `coder` models head-to-head, scored deterministically (no LLM
judges), logged to MLflow as directly comparable evaluation runs:

```bash
# one env-isolated subprocess arm per candidate + a printed ranking table
uv run --extra observability python -m evals.model_bakeoff \
    --models "glm-5.2:cloud,qwen3-coder-next:cloud" --limit 20

# a single arm (also what the parent spawns)
uv run --extra observability python -m evals.model_bakeoff --model glm-5.2:cloud
```

Per question: the live production-mirror pipeline (`run_golden` mode `full`)
generates SQL → executes → three scorers (`evals/mlflow_scorers.py`): golden
**execution accuracy** (multi-reference `sql_accuracy` comparator), the
**Trust-plane guard battery** (`aughor.trust.verify`), and **exec success** —
plus latency and kernel-metered tokens/question. Results land in the
`aughor-bakeoff` MLflow experiment (`AUGHOR_MLFLOW_TRACKING_URI`, or a local
file store under `evals/bakeoff_out/`) with per-question traces, and each arm
writes `evals/bakeoff_out/<model>.json` for the comparison table. Needs a
seeded `samples` connection and live LLM credentials.

## Golden dataset

`evals/golden.jsonl` — 15 Q&A pairs covering:
- **4** revenue/sales decline questions
- **3** customer behaviour questions (churn, acquisition, LTV)
- **3** product/category performance questions
- **2** operational questions (delivery, refunds)
- **2** direct lookup questions (should route to `direct` mode)
- **1** explore-mode overview question

All use `connection_id: "fixture"` (the built-in DuckDB sample warehouse).

## Ablation sets (`ablation_eval.py`, ROADMAP §3.15 ON-0)

One connection per file; every reference (and `accept_sql`) is executed before any model call.

| file | connection | status (2026-09-10) |
|---|---|---|
| `ablation_samples_ecommerce.jsonl` | `samples` (bundled) | 12 questions; run: 12/12 on every arm — a ceiling |
| `ablation_luxexperience_hard.jsonl` | `914df862/luxexperience` via `duckdb_path` | 14 questions, every trap's bite measured; run 2: raw 13/14 · ontology 13/14 · guards 100% safe — no lift, no loss (`ablation_on0_luxexperience_results.json`; run 1 kept as `…_run1.json`) |
| `ablation_missimi.jsonl`, `ablation_missimi_hard.jsonl` | `workspace/missimi` | the schema no longer exists on the instance — every reference fails, the harness skips them |

A record may carry `duckdb_path` (the LuxExperience demo pack, `data/luxexperience_demo.duckdb`,
see `docs/DEMO_PACK_DESIGN.md`) so the set opens the file read-only instead of the registry —
the registry is a served store, and a hermetic run beside the API redirects it. `connection_id`
stays the label and the `--graph-json` key; the served graphs are committed beside their sets
(`ablation_*_ontology.json`), and beside each the same graph after its relationship cardinalities
were measured against the data (`ablation_*_ontology_measured.json`, written by
`python -m aughor.ontology.cardinality` and then `python -m aughor.ontology.lifecycle`, each
`--graph-json <served> --duckdb <file> --out <measured>`; ON-0a). The measured files also carry the
core pack's claims by tier (`core_claims`), the receipt `POST /ontology/measure?pack=<id>` returns live. Run the `ontology` arm on the measured file to test a block that says true things. Run beside a serving API with every `AUGHOR_*_DB` redirected
(the list is `tests/conftest.py`'s) and `AUGHOR_FALLBACK_BACKENDS=none`.

## Adding questions

Append a line to `golden.jsonl`:
```json
{
  "id": "q016",
  "question": "...",
  "connection_id": "fixture",
  "expected_root_cause": "...",
  "expected_verdict": "confirmed",
  "expected_top_hypothesis_keywords": ["keyword1", "keyword2"],
  "notes": "..."
}
```

## How the agent is invoked

`run.py` calls `build_graph_generic()` directly — **no running server needed**. The LangGraph state machine streams events synchronously; the final `AnalysisReport` is extracted and scored.

## Accuracy measurement protocol (WS3, 2026-07-06)

**Hermetic gates (run automatically in CI — no LLM, no credentials):**
- `tests/integration/test_golden_reference.py` — replays all 53 golden records'
  `reference_sql` through the real scorer against a freshly-seeded fixture.
  Red = the dataset / fixture / scorer drifted (the measurement substrate broke).
- `tests/unit/test_ambiguity_eval.py` — pins the clarify-detector's recall +
  false-positive contract.
- `tests/unit/test_guard_counters.py` — pins the guard fire/repair counters
  (`guard.defan.*`, `guard.grain_fanout.fired`, `guard.join_domain.fired`,
  `guard.filter_bind.applied`, `guard.trust_e1.fired`, `sql_safety.*`), visible
  live at `GET /dev/stats`.

**Live pre-merge check (required for any change touching the answer path —
generation prompts, guards, schema linking, metric grounding):**
```bash
# once per machine/model: record the baseline
uv run python evals/ratchet.py run --mode full --set-baseline main
# before merging your change:
uv run python evals/ratchet.py run --mode full --name my-change
uv run python evals/ratchet.py check --baseline main --candidate my-change
```
The check fails on >2% accuracy drop or >15% token growth (see `ratchet.py`).
Golden-set caveats: temp-0 cloud models are still nondeterministic — treat
sub-2-pt deltas as noise unless replicated (`--runs 3` reports the band).
