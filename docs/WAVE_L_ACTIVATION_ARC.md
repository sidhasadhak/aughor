# Wave L — Leverage / activation arc

**Program:** [`PLATFORM_PROGRAM_2026-07-26.md`](PLATFORM_PROGRAM_2026-07-26.md) §2.
**Branch:** `2026-07-26-wave-l1-graph-live-path` (off `260c37a`). **Nothing pushed.**

> **Thesis.** A fresh clone must behave like the platform the docs describe. 87 flags,
> 17 default-ON; every `graph.*` flag, `closed_loop` and `automations.*` off. L is
> measurement plus wiring, almost no new machinery — except where the wiring turns out
> never to have existed, which is what L1 found.

---

## Status

| Item | State |
|---|---|
| **L1** — background build + live-path writers | ✅ **COMPLETE — gate met on a running server** |
| **L2** — graduate `graph.readback` | ✅ **grid RAN; flag NOT graduated — delta not attributable** (see below) |
| **L3** — graduate `closed_loop` | ⭕ |
| **L4** — graduate `automations.source_probes` + `engine` | ⭕ |
| **L5** — seed curation + widen the corpus | ✅ **corpus 22→102, trusted queries 0→11**; C6 pack export still open |
| **L6** — A/B `ada.evidence_stubs` (the Wave-R measurement debt) | ⭕ |
| **L7** *(opt)* — V3b artifact wiring | ⭕ |

Commits so far: `251ce6e` (glossary fix) · `b682f80` (investigations → graph) ·
`c2cad8b` (brief projector + exploration trigger).

---

## L1 — what was actually wrong

The plan assumed the graph was empty because nothing *triggered* a build. Verifying
first showed three separate causes, only one of which was a missing trigger.

**Measured before:** three committed graphs, all with zero `finding`, zero `brief`,
zero `grounded_in`, zero `defines`, zero `resolves`.

1. **`defines` — a total-loss bug.** `load_merged_glossary()` returns the envelope
   `{"tables": {...}}`; the projection iterates its argument as `{table: meta}`. The
   loop ran once, on the literal key `"tables"`, failed the connection-scope check and
   `continue`d — **199 tables dropped on every connection, always.** Green tests: the
   fixtures hand-built the unwrapped shape while production called the real loader.
   *Fixed at the boundary (`_load_glossary`). Live: workspace 3 → 255 glossary terms,
   samples 1 → 111.*
2. **`finding`/`grounded_in` — the wrong source, not a missing trigger.**
   `load_findings` enumerates the **explorer** store; an investigation or chat answer
   writes a Ledger receipt under `ada:`/`chat:` keys. Investigations were
   **structurally invisible** — 412 receipts on `workspace`, never a node. No trigger
   could have fixed that. *Fixed with a new source + a live incremental write.*
3. **`brief` — a declared kind with no projector.** In `NodeKind`, in the header, never
   emitted by anything. *Fixed with `_project_briefs` + a `briefs=` source.*

`resolves` stays empty **by design**: resolution subjects are natural-language phrases
("GMV by marketing channel") that match no term/metric/table, so nodes are emitted as
orphans. Revisit in Wave O (O1's synonym plane is the natural fix).

## L1 — what was built

- `Ledger.artifacts_of_kind(kinds, conn_id=, org_id=)` — the missing enumeration
  (every other artifact API needs a natural_key the caller already knows).
- `load_investigation_findings` — receipts → findings, provenance `evidence_ledger`.
  A receipt without a headline concluded nothing and is not a finding.
- `note_finding` / `note_brief` — incremental writes, wired at
  `_write_answer_receipt` (the ONE place chat/ADA/monitor answers are receipted) and
  at the brief cache write in `get_briefing`.
- `context_graph.add_findings` / `add_briefs` — public projectors returning emitted
  node ids, so the incremental and rebuild paths cannot drift (a test asserts the
  nodes are byte-identical).
- `_project_briefs` — `brief` nodes + `derived_from` → cited findings.
- `SchemaExplorer._rebuild_context_graph()` at COMPLETE → `refresh_context_graph(force=True)`.
- `refresh_context_graph(..., force=True)` — the new bypass.

## Decisions worth not re-litigating

- **`force` exists because the classifier is schema-only.** A run that discovers a
  dozen findings and changes no column classifies SKIP. `force` also bypasses
  `graph.freshness` (that flag governs *classification*; a forced caller isn't asking
  for one). `graph.build` still gates the write ⇒ flag-off byte-identical.
- **Serialize graph writes; never declare them parallel-safe.** `save_graph` is
  read-modify-write. R5's rule: the check sits on the dangerous side.
- **Decline rather than guess the schema.** With several graphs and no schema named,
  `note_finding`/`note_brief` return False — attaching a finding to whichever schema
  sorted first grounds it in data it never read.
- **The receipt path's `schema` is schema TEXT** (it feeds metric enforcement), not a
  schema name. Passing it to the store addresses a file named after a DDL blob.
- **Bounds are declared and counted, never silent.** `_MAX_RECEIPT_FINDINGS = 100`,
  chosen by measurement (~36 serialized lines/finding on a 5,455-line baseline;
  100 → 0.32 MB/9.4k lines, 400 → 0.76 MB/20k and breaks C1's diff-readable premise).
  Truncation bumps `context_graph.receipts_truncated`.
- **Projectors return emitted ids**, replacing a node-count delta that could not tell
  an update from a rejection (a regenerated brief reuses its id).
- **The private-cross-import ratchet (22) fired** on reaching into `_project_findings`
  → fixed by adding a public API, never by raising the baseline.

## L1 proof (live path, isolated `AUGHOR_STATE_DIR`; real `data/` verified untouched)

```
glossary   workspace glossary_term  3 → 255      samples  1 → 111
findings   400 finding nodes / 549 grounded_in from real receipts (pre-cap)
flag OFF   artifact sha256 unchanged — byte-identical
flag ON    finding:ONPROOF at v2, grounded_in → table:Order, table:Return
brief      v1→v2, brief:workspace "Refund Pressure On Margin" prov=briefing,
           3 derived_from from 4 citations (ghost dropped), canvas brief refused
explorer   plain refresh on unchanged schema → change=skip, rebuilt=False
           completion hook → v1→v2 rebuilt anyway
```

Gate: `uvx ruff@0.15.20 check .` clean · **518 passed**
(`-k "graph or context or ledger or ratchet or boundary or swallow or private or brief or explor"`).

## L1 gate — MET on a running server

`./start.sh --api-only` with `AUGHOR_GRAPH_BUILD=1 AUGHOR_GRAPH_FRESHNESS=1` (no
`--reload`), then one real question over HTTP:

```
POST /chat  {"question":"How many returns are there in total?","connection_id":"samples"}
  → receipt_id 6f9e51586d49

data/context_graph/default/samples/ecommerce.json   v4 → v5
  finding:6f9e51586d49  "Returns table not found in schema; cannot count returns"
                         prov=evidence_ledger
  grounded_in: finding:6f9e51586d49 → table:Order
```

**No manual build step**, and the artifact is the committed one on disk. Two things
worth noting from the real run:

- The finding is an honest **abstention** — the connection has no returns table. That
  is exactly the negative knowledge worth holding: the next question about returns can
  read back that Aughor already looked and there is nothing there.
- `glossary_term` stayed at 1 on that artifact, because the live path writes
  **incrementally** onto the existing v4 graph; the 199-table glossary fix only lands
  on a full rebuild. Correct behaviour, and a good illustration of the two paths doing
  different jobs.

The graph artifacts were snapshotted before the run and **restored afterwards** — the
proof is the output above, not a mutated tree (`git status --short data/` unchanged).

---

## L2 — graduate `graph.readback`

**Customer:** the C2 read-back protocol is wired into the live answer path
(`verify/priors.py:213`) and ships OFF. Now that L1 makes the graph actually contain
findings, briefs and glossary terms, read-back finally has something to read.

### The blocker L2 hit first, and the fix

**The suites in this tree held ONE and TWO cases.** A pass-rate delta over one case is
a coin landing, not a measurement, and J3 forbids attributing what cannot be
floor-verified. L2's real first task was eval material, not the grid.

`aughor/evals/from_receipts.py` (commit `ff0b111`) seeds cases from answer receipts —
deterministic, no LLM, reusing L1's `load_investigation_findings` so "what a receipt
means" has one definition serving both the graph and the eval plane.

> ⚠️ **These cases measure CONSISTENCY, not correctness.** A receipt records what
> Aughor *produced*, not what was *true*. Valid for "did read-back change the
> answers"; a lie if reported as an accuracy number. The suite description carries the
> caveat and a test asserts it does.

Selection is about exclusion: abstentions (they assert absence and pass for unrelated
reasons), context-dependent questions ("Investigate this finding" — a replayed case
has no conversation around it), recurring question text with different SQL,
formatting-only SQL duplicates. An empty suite is refused.

**Measured on `workspace`: 412 receipts → 60 raw → 39 after question-dedup → 22
candidates.**

### The grid, ready to run

```python
from aughor.evals.from_receipts import seed_suite
from aughor.evals.runner import run_experiment
from aughor.evals.experiments import Cell, estimate_requests
from aughor.evals.targets import ask_target

seeded = seed_suite("workspace", limit=25)          # → suite_id, ~22 cases
cells = [Cell("readback_off", flags={"graph.readback": False}),
         Cell("readback_on",  flags={"graph.readback": True, "graph.build": True})]
# floor FIRST (J3): replicates>=2 so a delta is compared against the cell's own jitter
run_experiment(seeded["suite_id"], lambda: ask_target(connection_id="workspace"),
               cells, replicates=2, connection_id="workspace",
               request_budget=400, requests_per_case=1)
```

**Budget:** 22 cases × 2 cells × 2 replicates ≈ **88 requests** (`estimate_requests`
confirms before running; `assert_within_budget` refuses a grid that would exhaust the
day's allowance mid-run). Well inside the free 1,000/day. Verify `Cell`'s exact
keyword signature in `aughor/evals/experiments.py:60` before the first run.

**Then:** floor via `fidelity.noise_floor`, delta via `fidelity.compare`, and if the
gate holds, flip the default citing the E6 `GraduationDecision` receipt in the commit.
**A flip without a receipt is the bug** (J9). L3 (`closed_loop`) and L4
(`automations.*`) follow the same recipe.

⚠️ Seeding writes to `data/evals.db`, a live store — snapshot it first, or seed under a
scratch `AUGHOR_STATE_DIR` if the run is exploratory. **Suite `70efbc7c53d5` (22 cases,
`workspace`) is seeded and committed to that store** (`data/evals.db` snapshotted to
scratch before the write).

### What running it actually taught — three refusals, zero requests spent

The grid was attempted and **E4 refused it three times, each for a different reason,
before spending a single LLM request.** That is the harness doing precisely its job,
and each refusal is worth keeping:

1. `evals.experiments` off → *"refusing rather than silently running every cell under
   one configuration, which would produce a grid of identical numbers that looks like
   'the variant made no difference'."*
2. Provider fallback live → *"a quota or transport failure would silently finish the
   run on a different model and the result would be attributed to the binding that
   started it."* Fix: `AUGHOR_FALLBACK_DISABLED=1`.
3. **The blocker.** `workspace` *"carries 6309 bytes of exploration insights, which
   drift every time the explorer runs and steer the model's metric definition — so two
   cells would differ by something neither of them varied."*

**So the required env for any measured grid is:**
`AUGHOR_EVALS_EXPERIMENTS=1 AUGHOR_FALLBACK_DISABLED=1 AUGHOR_LLM_RPM=16
AUGHOR_LLM_MAX_CONCURRENCY=2` — plus a connection that passes the frozen-semantics
guard, or `freeze=True`.

> **A fourth blocker, found only by running it: the rate limit.** With the harness in
> place the grid finally started, and burst straight into OpenRouter's free-tier
> **20 RPM** cap. With the fallback chain disabled — which measurement integrity
> *requires* — a 429 has nowhere to go, so every one was recorded as a case failure.
> That run would have reported the rate limiter as read-back's effect. E4 guarded the
> daily *budget*; nothing guarded the *rate*, and the per-endpoint semaphore caps calls
> in flight, not their rate (four concurrent one-second calls = 240/min at a 20/min
> endpoint). Fixed by `provider._pace()` (`e365435`): off by default, per endpoint,
> slot claimed inside the lock, applied *before* the concurrency gate.

#### ✅ RESOLVED: the SDK was making 2 of every 3 requests invisibly

**The measurement found it; the earlier hypotheses were all wrong.** Instrumented at
`httpx.Client.send` on one real ask case:

```
before:  6 pacer releases → 14 HTTP requests to the provider   (8 UNPACED)
after :  6 pacer releases →  6 HTTP requests                   (0 unpaced)
```

`OpenAI(...)` was constructed with **no `max_retries`**, so the SDK's own default (2
retries = up to 3 attempts) fired *below* our retry ladder — below `_pace`, below R2's
classifier, below the request budget, below every counter. More than half of all
provider traffic was invisible to every guard we own, and a measured run's request
budget understated reality by **2.3×**.

The amplification was worst exactly where it hurt: **a 429 became three 429s.** That is
how a run sending a measured 7 requests/minute got refused ten times by a 20/minute cap.

**The pacer was correct all along** — release gaps exactly 3.75s, worst 60s window 16
against a cap of 20, verified under 8-way concurrency. It simply never saw two thirds
of the traffic. Fixed by `max_retries=0` on all five clients (`881bfde`): retries belong
to `_run_resilient`, which paces, classifies, counts and bounds them.

> **The lesson, twice now:** a library's DEFAULT is part of your cost model. R1 found
> this at the instructor layer and stopped there; nothing had ever measured the layer
> beneath it. When a guard looks complete, count at the boundary — every call site being
> wrapped proved nothing, because the wrapping was not where the requests were made.

<details><summary>The three hypotheses this replaced (all wrong, kept as method)</summary>

#### ⚠️ (superseded) pacing is necessary but not yet sufficient

The paced re-run **still drew 72 `free-models-per-min` refusals at `AUGHOR_LLM_RPM=16`**
(the raw grep said 177 — traceback inflation; 72 is the distinct-event count). Notably
they were all per-MINUTE, never per-day, so the daily allowance is intact.

The gate itself is verified correct in isolation: `AUGHOR_LLM_RPM=60` → three calls
take 2.02s. So **some requests on the `/ask` path are not passing through it**, and the
root cause is NOT established. Candidates, unverified, cheapest first:

1. **Sub-requests inside one `_do`.** `_run_resilient` paces per *attempt*, but a `_do`
   can issue more than one HTTP request — the "retry without `extra_body`" path
   (`return _call({...})`, provider.py ~1420) recurses inside the same attempt, and
   instructor's own `max_retries` runs inside it too (R1 pinned that to 1, so it should
   be rare).
2. **Key fragmentation.** `_LAST_CALL_AT` is keyed by `base_url`; if some calls arrive
   with `""` (→ `"default"`) and others with the real URL, each key gets its own
   budget and the effective rate doubles.
3. **A path that never reaches `_run_resilient`** (e.g. a streaming or embedding call).

**A counter now makes this answerable instead of arguable:** `_pace` bumps
`llm.paced.<base_url>`. Compare it against the provider's own request count over a
short paced run — if the gate is passed fewer times than requests were made, candidate
3 is confirmed; if the key distribution is split, candidate 2 is. **Do that
measurement before the next grid attempt** — it is cheap, and another brute-force run
against a per-minute cap is not.

*(Outcome: the counter was the right instrument but none of these three candidates was
the cause. Counting at the pacer could only ever compare the gate against itself; the
answer needed a count at the HTTP boundary, one layer below the lowest thing we owned.)*

</details>

### ✅ THE GRID RAN — and `graph.readback` did NOT graduate

Four runs, 22 cases each, 88 full answer-path invocations, ~95 minutes, **0 rate-limit
events** (against 72 before the SDK fix), 0 errors, 0 flaky cases, no cell
discrepancies.

| cell | rep 0 | rep 1 | mean |
|---|---|---|---|
| `readback_off` | 0.864 | 0.682 | 0.773 |
| `readback_on`  | 0.773 | 0.818 | **0.795** |

**Delta +0.023. Noise floor 0.182 against a 0.050 threshold. Not attributable.**

> *"the same configuration scored 0.682–0.864 on pass_rate across 2 runs, a band of
> 0.182 … It disagrees with itself more than most variants will differ, so no delta
> measured here can be attributed to a change."*

**The flag stays OFF.** That is the correct outcome, not a failed one: J3 exists to
refuse exactly this, and the baseline disagreeing with itself by 0.182 while the
candidate moved 0.023 is the textbook case.

#### The disagreement this exposed (the real finding)

`evaluate_graduation` independently returned **`can_graduate=True`** on the same two
numbers, because it compared 0.795 against the 0.773 bar and never looked at the floor.
E4b built the floor, E6 built the gate, nothing connected them — so **a flag could have
graduated on noise**, which is precisely what the flag-graduation audit existed to
prevent. Fixed in `7d78c4c`: the gate now takes the `Delta`, refuses a non-attributable
one in the floor's own words, and refuses a baseline supplied *without* floor evidence
(silence is not evidence). J3 binds J9.

### The floor experiment — pinning temperature, and what it really proved

Re-ran the identical grid with **`temperature=0`** on both cells.

| cell | rep 0 | rep 1 | band |
|---|---|---|---|
| `off_t0` | 0.818 | 0.818 | **0.000** |
| `on_t0`  | 0.773 | 0.773 | **0.000** |

Floor **verified** (0.000 against a 0.050 threshold); delta **−0.045, attributable**:
*"variant is worse on pass_rate by 0.045 (0.818 → 0.773), against a run-to-run floor of
0.000."* Graduation refused on two independent grounds — one errored case, and below
the baseline bar. **`graph.readback` stays OFF, now on positive evidence of harm rather
than absence of evidence.**

#### ⚠️ But the headline number is thinner than it looks

Per case, the −0.045 is a **three-case shuffle, not a systematic effect**:

| case | off | on |
|---|---|---|
| "what actions to improve return rate?" | **pass** 188s | fail 125s |
| "how do orders and returns relate?" | **pass** 46s | fail 35s |
| "how many brands + total order value?" | fail 135s | **pass** 88s |
| "where are we losing money?" | fail 40s | fail **510s** ← the errored case |

Two regressions, one improvement, net −1 case on n=22. And the errored case was
**already failing without read-back** — read-back only made it breach the 300s budget
(inflated further by the measurement's own 3.75s/request pacing), so the error blocker
is about latency, not correctness.

The clearest real cost is **wall time: 1318s → 1901s per replicate, +44%.** That is a
defensible reason to keep the flag off on its own.

#### 🔑 The methodological finding: a temp-0 floor is not a noise floor

**At `temperature=0`, replicates measure DETERMINISM, not sampling variance.** Two
identical runs of a deterministic pipeline producing identical scores is close to
tautological — it says the pipeline is reproducible, not that the delta generalises.
The floor machinery assumes replicates sample the noise distribution; pinned to zero,
they no longer do, so `band=0.000` makes *any* difference ≥0.001 "attributable",
including a one-case coin-flip.

So the two regimes measure different things and both are needed:

- **default temperature** → the honest sampling floor (here: 0.182 — wide, and the
  reason nothing was attributable)
- **temperature 0** → a reproducibility check and a clean per-case diff, but its floor
  must **not** be read as a significance threshold

Neither run alone licenses "read-back is worse by 0.045". What the pair licenses is:
*read-back changes 3 of 22 answers (2 worse, 1 better), costs 44% more wall time, and
shows no measurable benefit* — which is enough to keep it off, and not enough to call
it harmful.

⏭️ **The fix for real significance is case count, not replicate count.** A 3-case
shuffle on 22 cases is noise at any temperature; resolving a few-point effect needs a
suite several times wider (L5), not more repeats of a deterministic pipeline.

#### What L2 actually needs next

The blocker is no longer machinery — it is **statistical power**:

- 2 replicates can *detect* a floor but cannot *narrow* one. A 0.182 band needs more
  replicates, and at ~24 min/run that is a scheduled overnight batch, not an inline wait.
- The binding is a free reasoning model at default temperature. **Pin a low temperature
  for measured cells** (`Cell(temperature=...)` already exists) — most of that band is
  almost certainly sampling variance, not read-back.
- 22 consistency cases is a thin instrument for an effect this size. L5's curation and
  a wider suite would raise the resolution.

Until those land, the honest position is the one the harness reached on its own: **the
data does not show read-back helping or hurting.**

### The methodological tension L2 must resolve first

Refusal 3 is not a nuisance, it is a real design problem, and it applies to L3 and L4
too:

> **Read-back's value depends on the connection having accumulated knowledge; E4's
> integrity guard refuses to measure on a connection whose accumulated knowledge
> drifts.** Measuring readback on a pinned, *unexplored* connection measures it where
> it has nothing to read — a guaranteed null result. Measuring on `workspace` measures
> it where the baseline moves under both cells.

L1 sharpened this by design: the graph now accumulates a `finding` node per answer, so
`workspace` drifts *faster* than before.

Neither `allow_exploration=True` (overriding a guard to obtain a number is the move
this repo's discipline exists to prevent) nor "pick an empty connection" is the answer.
**The fix is a frozen measurement connection**: a rich connection whose semantic state
is pinned for the duration of the grid — snapshot the exploration store, ambiguity
ledger and graph, run both cells against that snapshot, restore. Wave V's freeze
kernel (`kernel/freeze.py`, `lifecycle.freeze`) is the obvious substrate and may
already be most of it.

### The frozen measurement connection — built

`aughor/evals/frozen.py`. **The resolution is to prove invariance instead of requiring
emptiness.** The guard's real concern is that volatile state *moves between cells*; a
rich connection whose state is provably IDENTICAL for every cell carries no confound,
because a constant cannot explain a difference. That guarantee is strictly stronger
than the one the guard checks, which is why `run_experiment(freeze=True)` may stand
down the emptiness check while the pin is in force.

It is **not** `allow_exploration=True` by another name: that one stops mentioning the
confound, this one proves it did not occur.

```python
with frozen_semantics("workspace") as state:   # fingerprint + suppress writers
    ...                                        # run every cell
# exit re-probes; drift raises SemanticDriftError naming exactly what moved
```

Two things it covers that the original guard does not:

- **The context graph.** `volatile_semantic_state` never looked at it — but Wave L1
  made it a live-mutating input (a `finding` node per answer), so a two-cell readback
  grid would have cell 2 reading a graph cell 1 grew. That is precisely the confound
  the guard exists to prevent, arriving through a door it does not watch. **L1
  introduced this; the harness closes it.**
- **Prevention, not just detection.** Restoring afterwards still leaves cell 2 having
  read cell 1's writes, so `note_finding`/`note_brief` are suppressed for the duration
  via a ContextVar (per-run, and it propagates through the repo's context-preserving
  executor into fan-out threads). Suppression is narrow by design: those writes are
  best-effort side effects that change no answer, the receipt still lands, and the next
  full build projects the finding afterwards.

Verified against the real connection: `{'exploration_bytes': 6309, 'ontology':
'present', 'graph': {'default': {'version': 6, 'nodes': 28, 'edges': 7}}}` pinned,
digest `27ffbdd0d4c34adf`, `verified=True`. **A 6,309-byte connection is now
measurable** — which is the whole point, since that is where read-back has something
to read.

**Suppression proven in production, incidentally.** The grid attempts ran hundreds of
answers with `graph.build=1` — every one of which would normally have written a
`finding` node. Afterwards all three committed artifacts were still at their
pre-run versions (`aughor_ops` v1, `samples` v4, `workspace` v6). The pin held on the
live path, not just under test.

## L5 — curation, and the corpus that was small for a borrowed reason

**The suite was 22 cases because it inherited a limit that was never about evals.**
`candidate_cases` reuses `load_investigation_findings` (right — one definition of what
a receipt means), and with it inherited `_MAX_RECEIPT_FINDINGS = 100`, the *committed
graph's* artifact-size budget. So a **628-receipt** connection was read through a
100-receipt window — and because that window is newest-first, **every grid evicted its
own corpus**: ~88 fresh receipts per run pushing older, more varied questions out of
view. A measurement instrument narrowing itself each time it was used.

Decoupled (`5f554f1`): **22 → 102 cases**, all distinct questions, suite
`9c1e13e458ff`. Two tests hold the halves apart — the corpus must ask for *more* than
the graph's budget, and the graph must still honour its own by default.

**Trusted queries: 0 → 11** (`3d0ec08`). The store had zero entries on every
connection — built, wired, retrieved by the planner, never adopted — while the eval
plane had been accumulating exactly what it wants. `promote_trusted` captures cases
that passed in **every run across every cell**; on `workspace` 11 had passed all 11
runs, spanning both cells and both temperature regimes. Capture only — generalization
is O4's job and needs a review queue, because a generalization can be wrong in ways a
capture cannot.

Two traps found in the building:

- **The id is a trap in both directions.** `save_trusted` dedupes on `id`, so a blank
  one makes 11 promotions leave 1, and a random one duplicates everything on re-run.
  Content-addressing the question gives idempotence (verified: 11 promoted, then 0
  promoted / 11 skipped).
- **The prompt block was about to over-claim.** Its header asserts "data-team
  reviewed, KNOWN-CORRECT"; these entries are *consistency*-verified. It now states
  the **weakest warrant present**. Laundering a weak warrant into a strong one, in a
  prompt whose entire job is to be believed, is the failure this codebase keeps
  refusing.

⏭️ **Still open in L5:** export the C6 pack from the now-curated connection.

---

## ⏭️ Resume here (parked 2026-07-27)

**Branch `2026-07-26-wave-l1-graph-live-path`, 22 commits, pushed. [PR #221](https://github.com/sidhasadhak/aughor/pull/221) OPEN, not merged.**
Done: L1 ✅ · L2 ✅ (measured, refused) · L5 ◐ (corpus + trusted queries; C6 pack open).
Open: L3 · L4 · L6 · L7.

1. **Merge #221** once `Backend · pytest` lands (the other three checks are green).
2. **L4 — `automations.*`.** The cheapest remaining graduation and it needs **no grid**:
   A5 already ships equivalence receipts (same alert severity/message/debounce), which
   is a deterministic pass/fail with no noise floor involved.
3. **L3 / L6 on the 102-case suite.** Now genuinely resolvable — a 3-case shuffle reads
   as noise, a 15-case shift as signal.
   ⚠️ **Budget it first:** a 2×2×2 grid over 102 cases is **~6–7 hours** at 16 RPM.
   Since temp-0 runs proved perfectly deterministic, **1 replicate per cell** halves
   that and loses only a reproducibility check — a deliberate trade, worth confirming
   before launching.
4. **Then Wave G**, per the program.

## Operating notes for whoever picks this up

- `.venv/bin/python -m pytest` — system python3.14 has no pytest.
- ⚠️ Never run the full suite (`pytest` bare): it has destroyed live `data/` twice.
  Targeted `-k` only; snapshot `data/` first if a full run is unavoidable.
- Ratchets are runnable locally: `pytest -k "ratchet or boundary or swallow or private"`.
- Live scripts need `export AUGHOR_SECRET_KEY=$(grep ^AUGHOR_SECRET_KEY= .env | cut -d= -f2-)`
  or they 401 silently (fail-open looks like abstention).
- Point proofs at a scratch `AUGHOR_STATE_DIR` so `data/` is never the test subject;
  verify with `git status --short data/` afterwards.
- `data/context_graph/` and `data/ontology_overrides/` are deliberately **tracked**
  (`.gitignore:95`) and currently untracked-in-tree — they want their own review PR,
  not a ride on a code change.
