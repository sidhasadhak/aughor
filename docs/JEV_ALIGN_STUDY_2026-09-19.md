# Adoption study — `sutro-sh/jev-align`: the alignment loop around a typed judgment

**Date:** 2026-09-19 · **Subject:** <https://github.com/sutro-sh/jev-align> at `49753df`, MIT, ~4,000 lines
of Python source and ~2,900 of tests · **Companion:** `docs/TYPESAFE_JEV_STUDY_2026-09-17.md` (Arc JD)

## 0 · Why this is the +1, and not a repeat

The Jev/`jevlike` study answered **what shape a judgment should be**: one state, N independent typed
questions, a closed answer space, a probability per option, one forward pass. It stopped where every
such study stops — at the request.

`jev-align` answers the question after it: **where does the text of that judgment come from, and how
does it get better?** It is not a model; it is a governance design for the loop around one. A run is a
persisted, versioned, diffable *definition*; the model is a swappable backend; the system's entire job
is to improve that definition from human labels — and to be honest, at every screen, about what the
number it is showing does not prove.

Three things make it worth a day of reading. It is the first codebase in either study that treats **a
definition as an artifact with a lifecycle** rather than a prompt in a file. It schedules **human
attention by uncertainty** instead of by policy. And it is unusually disciplined about **the population
a number was measured on** — to the point of versioning that scope inside the saved report so an old,
incomparable number cannot silently join a new chart. That last one is a lesson this repository has
paid for more than once.

## 1 · Evidence, and its limits

First-hand: the full source at `49753df`, its 121 tests, `README.md` and `AGENTS.md`. Every file and
line reference below was read in this session.

Not first-hand: **no run was executed.** There is no `TYPESAFE_API_KEY` here, `docs.typesafe.ai`
remains blocked by this environment's egress policy, and running the loop would spend a reflection
model's tokens. So every claim about *behaviour* below is read off the code and its tests, not
observed; no claim is made about how good the resulting definitions actually are. The vendor's
accuracy figures carry the same caveat as in the companion study and are not repeated here.

The measurements of **Aughor** in §4 are first-hand and were taken today.

## 2 · The mechanism, stated precisely

A **run** is a directory (`.jev-align/runs/<id>/`) holding `state.json`, an append-only
`labels.jsonl`, prediction caches, per-round reports, GEPA artifacts and a `rewinds/` archive. The
definition inside it is a `TaskSpec` — for binary, `{instructions, true_criteria, false_criteria}`;
for multiclass, instructions plus one criterion per class; for score, instructions plus 2–10 ordered
levels; for multilabel, instructions plus a true/false criterion pair per label (`models.py:18-223`).

Each round:

1. **Score the whole frozen pool** with the current definition (`session.py:325-333`), reusing a cache
   whose key names every input the predictions depend on.
2. **Select the batch**: `batch_size - 1` most-ambiguous rows plus **exactly one seeded random audit
   sample** (`acquisition.py:34-61`, called with `exploration_count=1` at `session.py:360`).
   Ambiguity is `1 - 2·|p - 0.5|` for a calibrated probability, `1 - confidence` where the backend
   offers only native confidence, and the max over labels for multilabel (`acquisition.py:10-25`).
3. **A human labels every card.** No skip exists. `b` removes the previous label and steps back;
   `/back` leaves the rationale prompt. A rationale is optional and encouraged.
4. **GEPA proposes a new definition** from the accumulated labels and rationales
   (`optimizer.py:332-482`).
5. **The gate**: a report and a unified diff, then accept / reject / quit-and-resume
   (`cli.py:1779-1866`). Nothing auto-accepts. The docs say so twice, in both `README.md` and
   `AGENTS.md`: *"A higher training score never accepts a proposal automatically."*

Then the accepted function is loaded in the caller's application (`AIFunction.load(..., capture=True)`),
production calls are recorded as **observations**, and on the next resume they are offered as a second
pool to label. The recorded prediction is never treated as a label — `AGENTS.md` states this three
separate times, and `test_capture_learning.py` holds it.

### The four ideas, separated from the product

**(a) The definition is data.** It is a pydantic model, persisted, diffed with `difflib` and shown to
the human before it can replace its predecessor (`session.py:135-142`). Its history is a list of
`{round, candidate, decision ∈ seed|accepted|rejected, fit, holdout}` (`models.py:420-425`). GEPA sees
it as a flat `{component_name: text}` dict via `as_gepa()` / `from_gepa()`, and `from_gepa` **refuses a
candidate whose component set is not exactly right**, refuses one component's text that contains
another's marker (`level::`, `criterion::`, `label::`), and caps component lengths
(`models.py:122-151`). The optimizer is not trusted to preserve the schema; it is checked.

**(b) Uncertainty schedules human attention.** Not policy, not a queue, not a sample — the rows the
model is least sure about, plus one random row so the model's own blind spots can still be discovered.
That single random row is the whole design's falsifier: without it you only ever see rows the model
already flagged, and confident errors are invisible forever.

**(c) The gate shows what the number is not.** The report prints: training metric before/after,
held-out metric before/after when a holdout exists, ambiguity on the fixed pool, ambiguity on the
captured pool, ambiguity on the labeled replay set, a certainty bar per round across the whole run
history, GEPA's actual metric calls against the configured budget with the reason it stopped early,
and the diff (`cli.py:1642-1849`). Regressions are coloured even when the headline metric improved.

**(d) Production calls rejoin the pool as observations.** `capture.py` is a bounded, best-effort,
off-path JSONL writer: same selection rule as acquisition (ambiguity ≥ 0.8, plus a 5% audit of the
rest), a 256-record bounded queue, 64 KiB per record, 64 MiB per file, every rejection counted in
`dropped`, a disk error disabling the writer with exactly one warning, and **no extra model call ever**
(`capture.py:74-127`). Import deduplicates by a hash of the input fields, excludes the original and
holdout rows, refuses records whose field set does not match the run's configured columns, and reads
only the bytes present when the file was opened so a live writer cannot extend the scan
(`captured_inputs.py:23-127`).

### The economics, which are the hinge

Per round the loop spends roughly **one full-pool evaluation (1,000 rows by default) + GEPA's metric
budget (300) + two passes over the labeled set** — call it ~1,300 model calls — to buy **five human
labels**. That ratio is only sane because a Jev call is cheap and fast. This is the join between the
two studies: *the typed one-pass primitive is what makes the loop affordable*, and the loop is what
makes the primitive worth having. Neither half stands alone at a frontier decoder's price.

They do economise where it is free: on accept, the *proposed* pool cache is `os.replace`d into the
*current* slot, so the next round starts already scored (`session.py:579-589`).

## 3 · The engineering worth more than the product

These are transferable regardless of whether a single line of Jev is ever adopted here.

**A comparison across rounds needs a frozen population — and the scope belongs in the artifact.**
The whole original pool is re-scored every round; labeled rows leave *acquisition eligibility* only,
never the diagnostic (`session.py:335-338`). GEPA's batch sampler returns the **same ids** for every
evaluation in a round so batch-level F1 stays comparable when a parent is evaluated twice
(`optimizer.py:46-95`). And the payoff: every saved report carries `ambiguity_scope`, defaulting to
`"remaining_unlabeled"` when absent (`session.py:104-107`), and the history table **excludes** those
older rounds and prints why — *"used the old shrinking-pool diagnostic and are omitted because they are
not directly comparable"* (`cli.py:1687-1745`). A changed measurement was given a name, old artifacts
were labelled with the old name, and the chart refuses to mix them. That is stronger than anything in
this repository today.

**A cache key must name every input its value depends on.** `_load_pool_cache` returns `None` unless
the candidate, backend config, `source_sha256`, `selected_columns`, `column_mode`, the exact set of row
ids *and* the count all match — and it migrates a legacy `jev_model` key into the new backend shape
rather than accepting it silently (`session.py:238-284`).

**Turn off a third-party cache whose key does not match your score's population, with the reason in a
comment.** `cache_evaluation=False`, because each returned row carries a *batch-global* F1 and reusing
that score in a differently composed batch corrupts macro-F1 once the labeled set grows past five rows
(`optimizer.py:372-375`).

**Mutate one component at a time when components are semantically distinct.** `module_selector` is
`round_robin` for multilabel and score tasks, `all` otherwise — so a reflection about the whole rubric
is not pasted into every level's description (`optimizer.py:386-394`). Compare our own semops, where
25 rows share one prompt and a neighbour can move a row's verdict.

**Pin the third-party API you configure.** `tests/test_gepa_api.py` is 36 lines that construct the
exact GEPA config object and assert every field the code relies on still exists. An upstream rename
becomes a red test instead of a silent behaviour change.

**A backend declares what it can do, and is refused at the boundary when it cannot.**
`BackendCapabilities(task_types, uncertainty)` is a frozen dataclass; `validate_backend_for_task`
raises *before* a run starts if the provider cannot supply usable uncertainty for that task kind
(`backends.py:27-39, 119-131`). No provider SDK object crosses the seam: `Prediction` is
provider-neutral, and its model validator refuses to let binary, choice, score and multilabel shapes
mix in one object (`models.py:326-365`).

**Undo archives; it does not delete.** `archive_rewind` copies state, labels and captured inputs into
`rewinds/<utc-timestamp>-from-round-NNNN/` and *moves* the invalidated caches, reports and GEPA round
directories there (`persistence.py:98-130`). `rewind_previous_round` then restores the last `seed` or
`accepted` candidate, truncates labels and history, and **refuses to run while a decision is pending**
(`session.py:416-459`). Every write is atomic (`NamedTemporaryFile` + `os.replace`); labels are
`fsync`ed on append; `pop_last_label` raises unless the last saved record is the one the caller
believes it is (`persistence.py:69-75`).

**There is no skip.** A deliberate refusal, stated in `AGENTS.md`: a skipped item is an unlabeled row
that looks handled. Back, yes. Skip, no.

## 4 · What is true in Aughor today (measured, first-hand, 2026-09-19)

**The decision corpus exists and is nearly empty.** `data/decisions.db` holds **40 rows, all from one
site** (`converse.tool`). The other two registered sites — `ask.route` (`agent/nodes.py:172`) and
`framing.definition` (`agent/framing.py:98`) — have produced nothing on this deployment. Every row has
`source='llm'` and **`confidence = 0.0`**: the deciders offer no probability, so there is nothing to
sort a labeling queue by. Menus are 11 or 38 options wide.

**The loop has no return path.** `mark_outcome` (`aughor/learning/decisions.py:128`) has **zero call
sites** outside its own definition and tests. Every one of those 40 rows carries `outcome = ''`. The
menu and the pick are recorded; whether the pick worked is not.

**Grading has not moved in sixteen days.** `aughor/learning/exporters.py`'s docstring records a
measurement taken 2026-09-03: five verdicts, none carrying `sql_source` or `corrected_sql`. Re-measured
today: **still exactly five** — 2 accept, 1 correct, 2 reject — and still **zero** with `sql_source` or
`corrected_sql`. The arc's own prediction ("capture is already rich; grading is the gap") is holding,
and nothing is closing it on its own.

**There is no prompt optimizer anywhere.** No GEPA, no optimization loop over any prompt, in `aughor/`
or `evals/`.

**One piece is already better than jev-align's.** `aughor/agent/ambiguity_probe.py` generates candidate
interpretations of a question, **executes them**, and asks the human only when the results materially
diverge. Execution is the arbiter, not a model's self-reported probability. jev-align asks on
`p ≈ 0.5`; we ask when two readings actually disagree on real data. Where such an arbiter exists, ours
is the stronger design and should not be replaced by an uncertainty threshold.

## 5 · The findings, in value order

Each carries its receipt and its falsifier. These extend the companion study's JD series but are
numbered separately (**A1–A6**) because `ROADMAP.md` §3.19 is currently contested between Arc JD
(unmerged, `origin/claude/fervent-cori-w9ogfc`) and Arc IN — the section number is the user's call, not
this study's.

### A1 · The return path: `mark_outcome` gets called *(no vendor, no model, smallest diff here)*

Three `record_decision` sites, zero `mark_outcome` sites. A decision whose outcome is never written is
a row that can never be trained on, ranked by, or learned from — and the exporter beside it already
filters on exactly that. Wire the outcome at the sites where it is already known: a tool loop step that
errored, a route that was re-asked, a definition the user overrode.
**Receipt:** rows with a non-empty `outcome`, by site, one week after wiring. **Falsifier:** if no site
can say what "worked" means without a new judgement call, then the outcome is not free and belongs in
A2's human loop instead — say so and stop.

### A2 · Uncertainty schedules the human, not policy *(needs JD-1's probability)*

Today the only thing that routes work to a person is a *policy* gate — the 428 approval, the departure
hold. Neither knows which decisions were close. Once a decider emits its probability, the 40-row store
becomes an acquisition pool: show the N most ambiguous decisions plus **one random audit sample**, and
record the human's pick as the label. The audit sample is not optional garnish — it is the only way a
confident error is ever discovered.
**Receipt:** labeled rows per session, and the share of them that came from the audit slot and
*disagreed* with the model. **Falsifier:** if audit-slot disagreement is indistinguishable from
ambiguous-slot disagreement, the ranking is not reading anything and the queue may as well be random —
which is a real finding, and cheaper to run.

### A3 · A definition change is a diff, a score, and a named population *(no vendor)*

We already have `draft → proposed → approved` on metrics (`aughor/semantic/metrics.py:85`) and the
honest `formula_rejected` state. What is missing is the screen beside the ask. Today the departure gate
holds every Slack send because no approved metric defines `revenue`, and the user is asked for a
definition with no instrument next to the question. jev-align's `_decision_gate` is the shape of that
screen: what changed (diff), what it scored, **on which frozen population**, and what regressed even
though the headline improved.
**Receipt:** the same approval decision made with and without the report, on a metric that already has
a formula. **Falsifier:** if the report changes no decision, it is ceremony — drop it and keep the
plain ask.

### A4 · The frozen-population rule as a standing guard *(no vendor; this is the cheapest and it pays first)*

Store the measurement's *scope* in the artifact, and make any chart that spans rounds exclude — and
*say that it excluded* — the rows measured under a retired scope. This repository's memory carries the
scars: a catalogue is a measurement with a timestamp; two caps for one population; a briefing that
published two contradicting citations differing only by a `WHERE` clause. A named scope field would
have caught that last one at render time.
**Receipt:** one existing longitudinal surface (certainty, enforcement rate, grading volume) carrying a
scope tag, with a test that a mixed-scope series refuses to render as one line. **Falsifier:** none
needed — this is a correctness property, not a bet.

### A5 · Capture as a budget, not just a tolerated write *(no vendor)*

`record_decision` is already observation-never-control and already never raises — good. What it lacks
is a budget. jev-align gives its recorder a bounded queue, per-record and per-file byte caps, a counted
`dropped`, and a writer that disables itself after one warning on a disk error. We cap one field
(`_MAX_CONTEXT = 2000`); nothing caps the store's growth or tells us what we lost.
**Receipt:** a `dropped` counter that is non-zero under a synthetic flood, and a store that stops
growing at its cap. **Falsifier:** if volume never approaches any cap, the caps are free insurance and
the counter is the only part worth keeping.

### A6 · An optimizer over definitions — **not yet, and here is the number** *(hold)*

GEPA over a definition is the headline feature, and it is the one thing to refuse today. It optimizes
against *human labels*; we have five verdicts, none carrying `sql_source`, unchanged in sixteen days.
An optimizer on that corpus is an optimizer on noise, and it would spend a reflection model's tokens to
produce it. Build A1 and A2 first. Revisit when a single site has, say, 150 labeled decisions with
outcomes — the same order of magnitude MI-4's gates already use.
**Falsifier for the hold:** if a site accumulates that volume and a human-labeled holdout shows a
proposed definition beating the incumbent outside the noise floor, the hold is wrong and should be
lifted.

## 6 · What not to copy

**The label picker pre-selects the model's own answer.** `_prompt_label` places the menu cursor on the
model's prediction — the nearest score level, the labels it put above 0.5, its chosen class, or `t`/`f`
by which side of 0.5 the probability fell (`cli.py:1496-1578`). But the rows shown are, by
construction, the ones where the model is *least* sure. On a maximally ambiguous row the pre-selection
is a coin flip, and one Enter keypress records it as a **human label** that then becomes GEPA's ground
truth *and* the reported training score. That is automation bias built into the exact place the design
insists must be human, and it sits a few lines from a README that says "Every label comes from you."
It is cheap to fix — start the cursor unset, or on the *less* likely option — and it collides head-on
with this platform's standing rule that the definition is the user's call. Take the loop; refuse this
detail.

**The headline number is in-sample by default.** Training metrics are computed on exactly the rows GEPA
optimized against; the 20% holdout is opt-in and off by default. The UI does label the row "Training"
and both docs warn about it — but the default run's biggest number is a fit, not a generalization
estimate. If we build A3's report, the held-out column is not optional.

**The audit rate rides the global RNG.** `capture.py:89` calls bare `random.random()`, so a host
application that seeds or consumes the global RNG perturbs the 5% production audit. Acquisition, by
contrast, is properly seeded (`acquisition.py:56`). A recorder should own its own `random.Random`.

**The exploration slot is one row regardless of batch size.** `exploration_count=1` is hard-wired at
the call site (`session.py:360`), so the audit share falls from 20% at `--batch-size 5` to 5% at 20 —
silently, exactly when a user has opted into more labeling effort.

**And the gap the companion study already named: nothing here measures calibration.** The design sorts
by the probability, thresholds capture at 0.8 of it, and reports "certainty" as `1 - mean ambiguity` —
but nothing ever checks that 0.6 means 60%. jev-align inherits its probability's honesty as an
assumption. JD-4's battery (ECE plus the shuffled-context control) remains unbuilt in both codebases,
and it is still the instrument every other slice should be measured with. **`jevlike` owns the
instrument; `jev-align` owns the loop; neither owns the proof.**

## 7 · Verdicts

| # | Finding | Needs | Verdict |
| --- | --- | --- | --- |
| A1 | `mark_outcome` gets called | nothing | **Adopt** — smallest diff, unblocks everything else |
| A4 | Measurement scope named in the artifact | nothing | **Adopt** — correctness, not a bet |
| A2 | Uncertainty schedules the human, with an audit slot | JD-1's probability | **Adopt after JD-1** |
| A3 | Definition change = diff + score + named population | A4 | **Adopt** — it is the screen the departure hold is missing |
| A5 | Capture as a bounded budget | nothing | **Adopt, small** |
| A6 | GEPA over definitions | ~150 labeled decisions with outcomes | **Hold** — five verdicts is noise |
| — | Pre-selected label cursor | — | **Refuse** — automation bias where the human must decide |
| — | Hosted Jev binding | vendor | unchanged from the companion study: **hold** |

## Sources

- `sutro-sh/jev-align` at `49753df` — full source, 121 tests, `README.md`, `AGENTS.md`. Read first-hand
  2026-09-19; **not executed** (no `TYPESAFE_API_KEY`, and a run spends a reflection model's tokens).
- `docs/TYPESAFE_JEV_STUDY_2026-09-17.md` and `ROADMAP.md` §3.19 / §6 item 25 — on the unmerged branch
  `origin/claude/fervent-cori-w9ogfc` at `93112558`.
- Aughor measurements taken 2026-09-19 from this checkout and from `data/decisions.db` and
  `data/verdicts.db`, opened read-only.
- GEPA: <https://gepa-ai.github.io/gepa/>. TypeSafe's own documentation remains unreachable from this
  environment; no vendor figure is asserted here.
