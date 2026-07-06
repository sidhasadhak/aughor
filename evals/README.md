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

## Golden dataset

`evals/golden.jsonl` — 15 Q&A pairs covering:
- **4** revenue/sales decline questions
- **3** customer behaviour questions (churn, acquisition, LTV)
- **3** product/category performance questions
- **2** operational questions (delivery, refunds)
- **2** direct lookup questions (should route to `direct` mode)
- **1** explore-mode overview question

All use `connection_id: "fixture"` (the built-in DuckDB sample warehouse).

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
