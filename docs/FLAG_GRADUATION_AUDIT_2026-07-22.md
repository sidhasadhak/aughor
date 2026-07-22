# Flag-drift audit — 2026-07-22

**The finding:** 19 features were ON in one developer's runtime ledger while the code shipped them
OFF. Every fresh clone, every CI run, and every other user got none of them.

Two consequences worse than a stale backlog item:

1. **CI was validating a configuration nobody ran.** Every green suite exercised Aughor with all 19
   off — including the suites we treat as the merge gate.
2. **The daily-driver configuration was untested.** The thing actually being used was verified by
   nothing.

This is the platform review's "features stall at TESTED, not LEVERAGED" theme, measured.

## How the count was established

The runtime ledger (`data/system.db`, gitignored) held **28** overrides set to `True`. That number
over-states the drift, and the correction matters because it is the difference between a real
problem and a scary-looking one:

| Category | Count | Why it is not drift |
|---|---|---|
| Already `FLAG_DEFAULT = True` | 6 | Redundant override; a fresh clone gets them anyway |
| `AUTO_ELIGIBLE` | 3 | Turn on via their deterministic trigger; auto-mode is default-on |
| **Genuine drift** | **19** | Code default off, no auto path — only this machine has them |

Redundant six: `trust.verify_live` · `trust.verify_facade` · `capabilities.auto` ·
`capabilities.receipt` · `learning.receipt` · `ada.progress_events`.
Auto-eligible three: `ada.premise_check` · `ada.clarify_gate` · `ada.pin_canonical_metric`.

## The three graduation paths (they already exist)

1. **`FLAG_DEFAULT[name] = True`** — default-on for everyone; env `=0` or a runtime override still
   forces it off.
2. **`AUTO_ELIGIBLE` + `CAPABILITY_TRIGGER`** — on automatically when a documented deterministic
   trigger fires. The right path for a capability that should self-gate rather than always run.
3. **Delete the flag** — when the old branch is dead, the behaviour is simply how the product works.

## Disposition of the 19

### Batch 1 — GRADUATED 2026-07-22 (this PR)

All four are **deterministic** (no model in the loop, no extra query) and **byte-identical when
off**. That pairing is what makes a default flip safe to review: the default cannot change behaviour
except along its intended axis.

| Flag | Evidence |
|---|---|
| `intake.loss_signals` | 2026-07-16 A/B: a revenue ranking called the business "broadly healthy" over **2.4M CHF of refund leakage** and a 1.2M CHF utilization gap. Also forbids the un-computable verdict ("profitable" without cost data). |
| `report.argument_style` | `docs/REPORT_STYLE_STUDY_2026-07-16.md` (R16 P1) — deterministic re-composition of the same report data |
| `chart.exhibit_grammar` | 2026-07-16 chart-grammar study — exhibit spec computed from rows already fetched |
| `lens.decision_grade` | `docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md` (R15) — one bounded probe per table for the entity lens; no model |

`intake.loss_signals` is the load-bearing one: it does not add polish, it **fixes a wrong answer**.

### Intentionally OFF — not drift, and should stop being counted as such

| Flag | Why it stays off |
|---|---|
| `ai_sql` | Makes **per-row LLM calls**. Its own description says "enable deliberately". |
| `obs.mlflow` | Requires an external MLflow server (`AUGHOR_MLFLOW_TRACKING_URI`); default-on would be a no-op at best. |

### Decide with Wave E4 — each adds LLM calls for a claimed quality gain

These are exactly what grid experiments exist to settle. `closed_loop`'s own description already says
*"off by default until its delta is proven on your data"* — that is an E4 sentence.

`ada.why_deepen` · `ada.why_where_interaction` · `ada.causal_drill` · `closed_loop` ·
`explorer.synthesis_incremental`

### Cost-vs-latency — an operator's choice, not a default

Only `ada.parallel_why_lenses` is byte-identical output (fixed spec order, never completion order) —
a pure wall-clock win and the strongest candidate here. The rest change the answer or multiply
concurrent LLM calls, and defaulting them on while every provider is rate-limited would be actively
wrong.

`ada.parallel_lenses` · `ada.parallel_phases` · `explore.parallel_subq` · `ada.parallel_why_lenses`

### Own decision each

| Flag | Note |
|---|---|
| `agents.user_defined` | Deterministic and fail-closed (an agent with no documents sees none). Plausible graduate — default-on only makes the capability available. |
| `plan.program` | A whole alternate executor path (`/query/plan-run`). Needs its own soak. |
| `capability.pipeline_live` | An AL-02 live-migration flag — graduating it is a migration decision. |
| `specialist_packs` | "Off by default while the subsystem lands." Revisit when it has. |

## What Batch 1 changed, beyond the four defaults

Flipping a default makes the whole suite run in the new configuration, which surfaced three tests
that had silently encoded the old one:

- `test_exhibit_grammar_flag_defaults_off` / `test_flag_defaults_off` → now assert default-**ON**.
- Two "flag off" tests used `monkeypatch.delenv`, which under default-on now means **on**. They were
  changed to an explicit `=0`, so they test the **operator escape hatch** — the thing that actually
  matters once a flag is default-on.
- `test_ada_doc_has_rich_structure` lost its `keynums` block by design (the argument style bolds key
  numbers inline instead of emitting stat-tile rows) and now asserts the real default shape.

That last group is the audit's own justification in miniature: **three tests were describing a
configuration nobody was running.**

## Follow-ups

1. **Clear the 6 redundant overrides** from the live ledger. Harmless today, but a stale `True`
   would silently defeat a future deliberate flip to off. Not done here — it mutates live user
   state, and this PR should stay reviewable as code.
2. **A disposition ratchet.** Once all 19 are dispositioned, add an `INTENTIONALLY_OFF: {flag: why}`
   set and a test asserting every registered flag appears in exactly one of `FLAG_DEFAULT` /
   `AUTO_ELIGIBLE` / `INTENTIONALLY_OFF`. That converts "off" from a default into a declared
   decision, and is what stops this drift re-accumulating. Deferred until the dispositions exist —
   half a ratchet is worse than none.
3. **CI runs code defaults only.** Worth considering a second lane that runs with the intended
   production flag set, so the tested configuration and the shipped one stay the same thing.
