# B1 — probe-and-repair (SOMA's back half), built + the empirical finding

*2026-07-06. Companion to [`SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md`](SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md)
(the design spec) and [`SESSION_HANDOFF_2026-07-06.md`](SESSION_HANDOFF_2026-07-06.md) (the program
state). This records what shipped for **Option A / B1** and the live evidence it produced — which
turns out to matter more than the code.*

---

## 1 · What shipped

**`evals/spider2_probes.py`** — the probe-and-repair back half the candidates stage was missing,
built exactly to spec §2/B1 (I2 + I3 + I7), pure and offline-testable like `spider2_candidates.py`:

- **I2 · deterministic AST-diff disagreement extraction.** `extract_disagreements(sqls)` parses
  each live candidate with sqlglot, diffs a normalized clause-classed feature view, and emits the
  paper's `(dimension, options, evidence)` triples with **zero model calls** — classified into the
  taxonomy by construction: `AmbiValue`(literal) · `AmbiIntent`(grain / aggregation / window
  ·boundary) · `AmbiSchema`(column). Precision-first (like `grain_intent`): an operator-only delta
  is a boundary, not a value, ambiguity; a per-row→per-group transition is grain-only (the added
  aggregate is owned by the grain facet), so it doesn't spawn a spurious aggregation dimension.
- **I3 · deterministic-first probe battery.** `run_probes(...)` prefers the owned deterministic
  probe per facet (the harness wires `check_filter_value_domains` for AmbiValue and the execution-
  grounded `check_result_grain` for AmbiIntent-grain); an optional, capped LLM probe is reserved
  for the AmbiIntent residue (not wired in v1 — see §3).
- **I7 · evidence-typed repair gates.** `resolve(...)` adopts the evidence-consistent reading —
  cheapest first: an **existing candidate** a probe already prefers (free, no LLM), else a minimal
  `repair_fn` edit — and only if it clears **four deterministic gates**: (a) executes, (b) clears
  the probed dimension (re-run the probe), (c) doesn't regress an unresolved dimension *at
  subject granularity* (catches a same-class sibling — two literals, one untouched — that the
  class-level faithfulness gate can't see), (d) the AST-diff touches only clauses the cited
  evidence covers. Any gate fails ⇒ **keep the seed**. Monotonic by construction.

**`evals/spider2.py`** — `--probes` flag (gated on `--candidates > 1`); after candidate selection,
**only when `n_signatures > 1`** (disagreement is free evidence), runs `run_probe_repair(...)` with
deterministic grain+value probe adapters over the live connection and `SqlWriter` as the gated
repair. Agreement ⇒ ship the plurality answer, zero extra cost. A `probe_repair` trace step records
dims / resolved / source / gates for audit.

**Tests:** `tests/unit/test_spider2_probes.py` — 19 offline, pure (no DB, no LLM): taxonomy
classification per facet, the four gates, the free-alternative-before-repair preference, and the
never-go-backwards contract. Plus controlled real-SQLite smoke tests proving both deterministic
paths **adopt** correctly (value → swaps to the value present in the data; grain → swaps to the
per-group reading; all gates green) and that an agg-only disagreement with no deterministic
resolver keeps the seed. `uvx ruff` clean; 207 sql/eval unit tests green, no regressions.

---

## 2 · The live finding (the part that matters)

Ran 5 instances through the real pipeline (glm-5.2:cloud, `--candidates 4 --probes`):

| id | signatures | B1 | extracted dimension(s) | outcome |
|---|---|---|---|---|
| local007 | 1 (agreed) | no-op | — | ship plurality, 0 cost ✅ |
| local018 | 1 (agreed) | no-op | — | ship plurality, 0 cost ✅ |
| local021 | 2 (disagree) | **fired** | AmbiIntent/grain | probes couldn't resolve → **kept seed** |
| local008 | 3 (disagree) | **fired** | AmbiIntent/grain + aggregation | kept seed |
| local015 | 3 (disagree) | **fired** | AmbiIntent/grain + aggregation | kept seed |

Every mechanism worked as designed: agreement is a free no-op; disagreement triggers extraction;
the taxonomy classification is right; **zero regressions** (B1 never shipped a worse answer than
the seed). **But on every disagreeing miss, the dimension was `AmbiIntent` (grain-of-intent), and
the deterministic probes could not resolve it** — because the ambiguity is *inside the aggregation*
(local021: per-match vs per-career totals that both collapse to one average row), invisible to a
row-count grain probe, and there was **no `AmbiValue` disagreement** — the one class the
deterministic value probe would have adopted.

This is not a bug; it's the measurement. And it lines up exactly with the Phase-0 fail-analysis:
**wrong_values = 49/63 misses (78%), all "grain-of-intent ambiguity."** The residual Spider2 errors
on glm-5.2 are dominantly semantic-intent ambiguities where:
- the disagreement signal *exists* (B1 sees it), but
- **execution probing can't settle it** — the readings differ in meaning, not in a wrong literal or
  a wrong output shape. This is SOMA's own admitted blind spot (convergent-or-intent ambiguity),
  and for a definition question ("what does *total runs by a striker* mean") the ground truth is
  the **question/definition/human**, not the database.

---

## 3 · What this implies for the next move

The deterministic B1 core is correct, monotonic, and **the honest inference-time experiment is
essentially concluded**: it adopts only where execution evidence proves an edit, and on this
benchmark's residual misses that evidence mostly doesn't exist. Two forward paths, and the live
evidence **shifts weight toward the second**:

1. **The capped LLM AmbiIntent probe (spec I3 residue, ≤3 calls).** The hook exists (`run_probes`
   takes `llm_probe`); it is deliberately unwired. **Caution:** an LLM that picks the intent-correct
   reading is exactly the *judge-selection* mechanism SOMA shows is +7.0 **worse** than probing, and
   it reintroduces the non-determinism the noise-floor analysis warns about. It must not be shipped
   on faith — it faces the standing controlled protocol (same-instance on/off, sentinels, monotonic
   or it dies), same as the two levers that died this week.
2. **Option B — the Ambiguity Ledger + I4 clarification (the durable play).** The live finding is
   the strongest argument yet for it: the dominant residual is *intent* ambiguity, whose true
   resolver is a human/definition (SOMA's Proposition 1 ceiling), and whose value is **permanent
   once resolved** (ledger) rather than re-litigated every run. Immune to the benchmark noise floor.

**Recommendation:** treat B1-deterministic as done and merged-ready (additive, flag-gated,
monotonic, well-tested). Do **not** bolt on the LLM AmbiIntent judge without a measured A/B. Pivot
to **Option B** — the live evidence says the compounding, human-confirmed resolution is where the
residual accuracy actually lives.

---

## 4 · The measurement command (the gate, when endpoint-hours are available)

The controlled A/B that would formally score B1 (per the standing protocol — never a misses-only
run; sub-10-instance deltas are noise on glm-5.2):

```
# same instances, probes OFF then ON, candidates fixed at 4; score both with the official evaluator
uv run python evals/spider2.py --ids <disagreeing-subset> --candidates 4          --outdir evals/spider2_b1_off
uv run python evals/spider2.py --ids <disagreeing-subset> --candidates 4 --probes --outdir evals/spider2_b1_on
uv run python evals/spider2.py --score --outdir evals/spider2_b1_off
uv run python evals/spider2.py --score --outdir evals/spider2_b1_on
```

Prediction from the live finding: on the current deterministic-only wiring, `on` ≈ `off` (B1 keeps
the seed on the AmbiIntent-intent misses it can't resolve; it only moves value/grain-by-rowcount
cases, which are rare in the residual). The endpoint throttles (~5 inst/hr sustained) — run the
disagreeing subset, not the full 135. Outputs are gitignored.
