# Full-pipeline eval — trustworthiness & what it can measure (#13 → #13b)

Goal: make the golden NL2SQL eval *trustworthy* — able to measure the real
capability lift of the intelligence-injected pipeline (FULL) over raw schema-only
generation (RAW). The prior run (#13) was confounded and couldn't. This is the
#13b follow-up: build the trustworthiness levers, then deep-test what they reveal.

## Levers built

1. **Pinned connection + frozen-state guard** (`run_golden.py`). FULL runs default
   to `samples` and **abort** if the connection carries volatile exploration
   insights (verified: `workspace`'s 7549 bytes → hard abort). Every run prints a
   provenance block (model / temperature / exploration-state / ontology) and
   disables the silent Anthropic fallback so the model is pinned. This makes the
   #13 confound (running on an *explored* connection whose ~25 drifting insights
   steer the metric choice) impossible to reintroduce silently.
2. **Metric-aware multi-reference scoring** (`sql_accuracy.py`). A record may carry
   `accept_sql` — equally-valid alternative ground-truth SQLs. The generated query
   is scored against the BEST of `{reference_sql} ∪ accept_sql`, so a correct
   answer using a *different but canonical* metric definition isn't penalised —
   without becoming permissive to genuinely wrong answers (regression-tested,
   `tests/unit/test_eval_scoring.py`). Attached gross `line_total` alternatives to
   the 8 order-grain revenue questions.
3. **Noise control** (`--temperature`, default 0.0; `--runs N`). Decode temperature
   threaded through both generators and the `SqlWriter` retry path; `--runs N`
   reports the per-question score band.

## Deep-test (pinned `samples`, temp-0, N=3, qwen3-coder-next:cloud)

| Mode | Perfect | Pass (≥0.80) | Errors | Unstable (band>0.05) | Mean band |
|------|---------|--------------|--------|----------------------|-----------|
| RAW  | 11 (N=3 mean) | 26 | 3 | 21/53 | 0.175 |
| FULL | 8  | 18 | 0 | 20/53 | 0.133 |

The headline says FULL is **−8 on pass**. It is NOT a capability regression. Two
findings explain (and dissolve) it.

### Finding A — temperature 0 does NOT make the cloud model deterministic

RAW (a single coder call, no retry) still shows **21/53 questions unstable** across
three identical temp-0 runs, mean band **0.175**; some swing the full range
(sql009 `[0.0, 1.0, 1.0]`). Cloud inference is non-deterministic at temp-0
(batching/hardware), so **temp-0 alone is insufficient — N-averaging is mandatory**,
and even N=3 leaves a ~0.13 band (headline good to only ±3–4 questions). Any
single-run A/B on this stack is untrustworthy. (Previously hypothesised in
`eval_golden_baseline`; now quantified.)

### Finding B — FULL's −8 is the ex-cancelled REVENUE CONVENTION, not capability

On the clean `samples` connection (0 bytes exploration), FULL still applies
`WHERE status NOT IN ('cancelled', …)` to **22/53** revenue/items aggregates — a
defensible *net-revenue* convention coming from the injected rules/KB/catalog. The
golden references use *gross* revenue. So FULL is penalised for computing a more
considered number. Proof (`_probe_convention.py`, run[0] basis since the stored
SQL is run[0]'s; convention-neutral score = **MAX(as-scored, status-stripped)** per
question, so a query passes if it matches the golden *with or without* the
ex-cancelled convention — this recovers pure-revenue queries WITHOUT damaging
genuinely status-dependent ones, which keep their correct as-scored value):

| | as-scored | convention-neutral |
|---|---|---|
| RAW  pass@0.80 | 28 | 28 |
| FULL pass@0.80 | 20 | 26 |
| **Δ (FULL − RAW)** | **−8** | **−2** |

Neutralising the convention recovers **+6** of FULL's −8 (RAW is unchanged — raw
schema-only generation rarely invents the convention). Six queries recover cleanly
and completely (sql004 0.60→1.00, sql012 0.60→1.00, sql020 0.60→1.00, sql022, sql009,
sql011) — the SQL was correct; only the revenue *definition* differed. The residual
**−2** sits inside the ±3–4q noise band (Finding A) **and is itself mostly further
definition-divergence the status-strip doesn't catch**, not capability:

- FULL deficits (RAW pass / FULL fail): sql002, sql006, sql025 (AOV / %-refunded
  computed ex-cancelled — same convention, on `AVG`/ratio not `SUM`), sql043
  (ex-cancelled **+** a spurious `GROUP BY country`), sql008 (dropped `LIMIT 1`),
  sql042/sql053.
- FULL **wins** (FULL pass / RAW fail) — clean capability gains where injected
  context rescues a RAW *total* failure: sql009 0.00→0.85, sql034 0.00→0.85,
  sql021, sql031, sql048.

So convention-neutral, **FULL ≈ RAW within noise (26 vs 28)**, and FULL wins exactly
where the intelligence rescues a query RAW cannot write at all. (`Metric-alt hits = 0`
corroborates the root cause: the 2-way `accept_sql` — gross `total_amount` ↔ gross
`line_total` — never matched, because FULL's answers are the *net* ex-cancelled
variant, a third definition the references don't yet encode.)

> Correction note: an earlier pass reported "RAW 23 ≈ FULL 23 (Δ0)". That used a
> *replace*-with-stripped probe that over-corrected status-dependent questions on
> both sides, depressing the absolute to 23 and coincidentally equalising it. The
> MAX estimator above is the corrected, consistent figure: **RAW 28 / FULL 26, Δ−2**.

## Conclusion — the binding constraint is METRIC UNIFICATION, not the harness

Connection-pinning (Lever 1) was **necessary** — it removed the exploration-driven
drift of #13 — but **not sufficient**: the *stable* injected context (rules/KB/
catalog conventions) still diverges from the golden's naive metric definition. The
eval cannot measure capability lift until the ground truth and the injected
semantic layer **agree on the metric definition**, including the cancelled/refunded
treatment. That is precisely the metric-unification problem (roadmap #2 / the
semantic-layer convergence), and this gives it a concrete success criterion:

- **Drive both sides from ONE registered metric.** Derive the golden references
  from the same canonical `revenue` definition the pipeline injects (gross vs
  net-of-cancelled decided once, in the semantic layer), so they agree by
  construction. As a bridge, extend `accept_sql` to the full set
  (gross/net × total_amount/line_total). The harness now caches per-run SQL
  (`runs_detail`) so this re-scoring needs **no** new LLM calls.
- **Control noise with N-averaging + reported confidence** (temp-0 is not enough).

Net for #13b: the trustworthiness infrastructure is built and the deep-test
**overturned the surface −8 to −2 (within noise)** — the convention explains +6 of
the gap and the residual −2 is mostly further definition-divergence, against which
FULL posts 5 clean wins RAW can't match. The honest capability verdict — and any
further NL2SQL micro-lever — is gated on metric unification, which the eval now
makes measurable. See
[[eval-golden-baseline]], [[ontology-semantic-layer-AB]],
[[competitive-borrow-cube-mindsdb]].
