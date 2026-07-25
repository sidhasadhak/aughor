# The proxy-inversion audit

*Wave E4 loose end. Code: [`aughor/evals/proxy_audit.py`](../aughor/evals/proxy_audit.py);
the composite lever is `demote` on [`fidelity.assess`](../aughor/evals/fidelity.py).*

## The failure it prevents

An eval axis is one of two things: the **end task**, or a **proxy** for it. Optimising a proxy
is safe only while the proxy tracks the end task — and a proxy can stop tracking it. When it
does, improving the proxy moves the true metric the *wrong way*. That is proxy **inversion**, and
it is how a change that made the product worse ships behind a green number.

The case study (from the five-repo study, §3, REFRACT's quantization work): on gemma-4 instruct
models, quantized KV cache scored **7–42% *better* corpus perplexity** than the fp16 reference
while **KL divergence said it had drifted the *most***. Perplexity — an *absolute* proxy with no
anchor to the reference distribution — read miscalibration as improvement. The lesson REFRACT
drew, and the reason it scores every axis as *distance from the same model's fp16 self* rather
than absolutely: **absolute proxy metrics can invert, so never let one stand in for the end task
unaudited.**

Aughor has already measured its own version of the trap. E2's evaluator sweep over the 53 golden
queries found guards firing on **known-correct SQL** — true positives in our *own* reference SQL
(the CIDR "benchmarks are broken" pattern), plus false positives on safe 1:N aggregation. So a
rising `pass_rate` (fewer guards firing) does **not** imply rising correctness, and can move
against it. E3 had already separated the two claims ("guard-clean" ≠ "correct"); this audit makes
the harness act on that separation.

## The taxonomy (the audit's conclusion)

| Axis | Kind | Why |
|---|---|---|
| `accuracy` | **ground truth** | execution exact-match (`user_agents.quality.results_match`) on the result set — the end task itself. Never demoted; it is what every proxy is judged against. |
| `pass_rate` | **proxy** | guard-clean stable passes. Guards fire on known-correct SQL (E2), so it can move opposite to `accuracy`. |
| `robustness` | **proxy** | agreement under meaning-preserving perturbation. A *consistently wrong* pipeline scores high — orthogonal to correctness, not a stand-in for it. |
| *(unclassified)* | **proxy** | the safe default. Assuming an unknown axis is the end task is the exact mistake this audit prevents. |

## The mechanism

Two steps, mirroring REFRACT's "trust the direction, not the decimals":

1. **`audit_inversion(runs)`** — over an *ordered* run history (a grid's baseline-then-variants,
   or a suite's runs in time order), each consecutive pair is one observation. A proxy that
   improved by more than `epsilon` while `accuracy` fell by more than `epsilon` is an
   **inversion**. A proxy with `inversions > 0` over `>= min_pairs` observations is **demoted by
   evidence**. Below `min_pairs` the verdict is `None` — evidence too thin to convict *or* clear —
   and the proxy is demoted only when a caller explicitly asks for a task-anchored composite
   (`demote_unproven_proxies=True`). The ground-truth axis is never demoted.

2. **`assess(cells, …, demote=report.demoted_axes())`** — a demoted axis is kept out of the
   harmonic composite, so a variant that only moved a proxy cannot score higher. The axis is
   still measured and its delta still reported — a reader sees the proxy — it just no longer
   inflates the single number. Default `demote=()` is byte-identical to the pre-audit harness.

## Why it matters, in one line of output

Same grid, assessed both ways — a variant that raised `pass_rate` 0.5 → 0.9 while `accuracy`
held at 0.9:

```
composite NAIVE   : baseline=0.643  variant=0.900   ← the proxy inflates the "variant is better" story
composite ANCHORED: baseline=0.900  variant=0.900   ← demoted, the proxy-only win is gone
```

The naive composite would graduate a change that did nothing for the end task. The anchored one
refuses. That refusal is the whole product.
