# Specialist Agents — Taking it 10x

*Companion to [`DOMAIN_EXPERTISE_PACKS.md`](DOMAIN_EXPERTISE_PACKS.md). Drafted 2026-06-26.*

> **Thesis.** v1 makes aughor *configurable per domain* — a themed lens authored once. The
> ceiling is low: the folder format is copyable in a weekend, and a pack is only as good as the
> day it was written. The 10x is not more pack features — it is changing **what a specialist is**:
> from a static config object into a **self-improving, trust-earning teammate** inside an **expert
> organization**, distributed as a **portable, re-grounding network**. The defensible asset stops
> being the folder and becomes the thing competitors can't copy: thousands of grounded, *verified*
> runs compounding into experts that are correct on any warehouse.
>
> **But the whole tower rests on one assumption — that the base engine's investigations are
> trustworthy. They are not, reliably.** So the real foundation is not a bet at all; it is the
> verification substrate below all of them. That is §0, and it must ship first.

Every section below carries a **build · wire · test · leverage** evaluation (the project principle:
a capability is real only when it is BUILT, WIRED into the live path, TESTED, and LEVERAGED — proven
to change the real output) and an explicit **UI** surface, because a guard the user can't see is a
guard they can't trust or act on.

---

## §0 · Why the base engine must verify itself (the real foundation)

Investigations **will** go wrong — that is a given, not a risk to engineer away. On one Swiss-Air
run we found 13 distinct failures, and one (`_attach_stats` silently dead) meant a guard was *off
and nobody knew*. The question is therefore not "how do we make investigations never wrong" but:

> **How does the system know when it's wrong, contain the blast radius, and refuse to compound or
> act on what it hasn't verified?**

### 0.1 The two dangers the 10x vision creates

1. **The flywheel inverts the cost of a wrong run.** Today a bad investigation is one bad answer.
   With self-distilling experts (Bet 1), a bad run becomes a *permanent wrong belief* the expert
   compounds. Base correctness matters **more** the more autonomous we go, not less.
2. **Self-graded trust is circular.** The Swiss-Air run was emitted at *High confidence* and was
   wrong. A system that scores its own confidence is overconfident in exactly the cases it errs.
   Trust must be calibrated against signal *external* to the thing being tested.

### 0.2 Name how a run goes wrong (you can't defend what you can't classify)

| Class | Example (Swiss-Air / the 13 fixes) |
|---|---|
| **A. Wrong framing / routing** | answers a different question; temporal-change misrouted to cross-section |
| **B. Wrong SQL / grounding** | cardinality (COUNT/COUNT over join), fan-out, wrong grain, cross-schema leak |
| **C. Right SQL, wrong reading** | eyeballed significance; noise called a driver; € shown for CHF |
| **D. Right facts, wrong synthesis** | "structural" on single-month data; contradictory recommendations |
| **E. Silent feature failure** | `_attach_stats` dead — every *other* guard assumed it ran |
| **F. Garbage input** | suspicious uniformity; single reason value; one time period |

The 13 fixes were **point defenses**, scattered across A–F. Class E proves point defenses are not
enough: when a guard silently turns off, every conclusion downstream is *falsely* "checked." We need
a layer that notices.

### 0.3 The verification substrate (Bet 0) — seven mechanisms

Each generalizes something we already shipped from a one-off patch into a measured property.

| # | Mechanism | Defends | Seed already shipped |
|---|---|---|---|
| 0.1 | **Adversarial self-verification** — an independent skeptic pass must *try to refute* a High finding (re-derive differently, hunt the confound); survive or be demoted | B/C/D | — |
| 0.2 | **Triangulation / reproduce-by-independent-path** — a number is trusted when two structurally different queries agree (rate via `COUNT/COUNT` vs `COUNT(DISTINCT)`); divergence → flag, don't conclude | B | count-ratio guard (#9) |
| 0.3 | **Calibrated confidence, not asserted** — a computed score from significance, CI width, sample size, reproduction agreement, eval history, *with provenance* — replaces "High" the vibe | C/D | significance/uniformity primitives (#1/#2) |
| 0.4 | **Falsification log** — every conclusion records the tests it *survived* and those *not run*; "structural across all dimensions" is only emittable if the independence tests actually ran | D | no-signal + completeness guards (#1/#6) |
| 0.5 | **Liveness / wiring assertions** (the class-E defense, the novel one) — the system proves *its own guards fired*; a run that skipped a check is labeled "not verified by X", never silently trusted | E | the `_attach_stats` fix |
| 0.6 | **Data-trust gate** — sanity-check inputs *before* concluding (uniform? single-valued? one period?) and *cap* the confidence of anything drawn from suspect data | F | uniformity red-flag + temporal prune (#1/#7) |
| 0.7 | **Human ground-truth capture** (the non-circular anchor) — an analyst's verdict ("that's a billing artifact") is captured as a label; trust is scored against accumulated verdicts + triangulation, never self-assessment | all | — |

### 0.4 The architectural rule that saves the tower

**Nothing consumes a run above its earned trust.**

| Consumer | Requires |
|---|---|
| **Answer** the user | any tier — confidence scaled honestly to caveats |
| **Compound into an expert** (flywheel) | *verified runs only* — breaks garbage-in-compounded-garbage |
| **Autonomous action** | verified **and** the action is reversible or human-gated — contains blast radius |

A run that didn't survive refutation, drew on suspect data, or whose guards didn't all fire is
**quarantined**: usable for a caveated answer, never as a learning or an action.

### 0.5 The honest ceiling

We never get an oracle, and chasing one is the wrong goal. What's achievable — and sufficient — is a
system that is **calibratedly uncertain**: when unsure it says so, it fails *loud* (class E is the
enemy), and no unverified conclusion drives an irreversible step. The Swiss-Air failure wasn't that
it was wrong — analyses are sometimes wrong. It was wrong *and confident and unguarded*. Bet 0 makes
"wrong-and-confident-and-acted-on" structurally impossible while leaving "wrong-but-flagged" fine.

### 0.6 Build plan — Phase 0, in shippable increments

| Increment | Deliverable | build · wire · test · leverage | UI |
|---|---|---|---|
| **0-I (this arc)** | **Run Verification Manifest** — record which checks fired per run (significance, join/cardinality guard, uniformity, temporal prune, stats attach) | build: a `VerificationManifest` record + recorder hook; wire: stamped through the explore graph + into the report; test: unit (a skipped check shows as not-run) + the `_attach_stats` regression; leverage: the manifest appears on a real report and a missing check is visible | **Verification panel** on the report: "checks run ✓ / not run ⊘" |
| **0-II (this arc)** | **Earned confidence + data-trust score** — pure function over manifest coverage + significance/uniformity/completeness/cardinality signals; data-trust caps it | build: pure scorer + data-trust detector; wire: into synthesis, attached to report; test: Swiss-Air shape → low earned confidence + low data-trust; leverage: the report's confidence reflects the score, not the LLM's vibe | **Trust meter** + "why this score" provenance on the report |
| 0-III | **Triangulation** — for a rate/ratio finding, auto-run the independent-path variant and compare | build: variant generator + agree/diverge check; wire: explore finding path; test: cardinality case diverges; leverage: a divergent run is flagged, not shipped | divergence badge on the finding |
| 0-IV | **Adversarial self-verification** — skeptic LLM pass on High findings | build: refute-prompt + verdict; wire: pre-emit gate; test: a noise "driver" gets demoted; leverage: confidence drops on a real refuted finding | "survived N refutation checks" on the finding |
| 0-V | **Human ground-truth capture** — accept/correct/reject a finding → labeled verdict store | build: verdict store (org-keyed); wire: report actions → store; test: verdict round-trips; leverage: a captured correction changes the next run's confidence | accept / correct / flag controls on each finding |

Increments 0-I and 0-II ship in this arc. 0-III–0-V are the next slices and gate Bet 1.

---

## The seven bets (ranked by leverage; all ride on §0)

For each: **from → to**, the unlock, why only aughor, the new seam, **UI**, and a **build · wire ·
test · leverage** note.

### Bet 1 · The flywheel — self-distilling experts *(the moat; gated by §0)*
- **From** a pack authored once → **to** a pack that rewrites itself from its own *verified* runs.
- **Unlock:** a `pack-learning` distiller proposes versioned pack deltas (caveats, binding
  corrections, new diagnostics) from run receipts + human verdicts. On day 90 the expert is far
  sharper than day 1, and that delta lives in *our* grounded run history.
- **Why only aughor:** the deltas are grounded + verified (§0) + eval-gated (Bet 2), so the loop
  compounds learning, not drift.
- **Seam:** distiller over Governed Dives + `_learn_from_exploration` writeback + Trust Receipts.
- **UI:** an expert "changelog" — what it learned, from which run, accept/revert per delta.
- **build·wire·test·leverage:** build the distiller as a pure proposer; wire it to consume *only
  manifest-verified* runs; test that an unverified run yields no delta; leverage = a real run's
  learning visibly sharpens the next answer.

### Bet 2 · Evals-as-spec — test-driven specialists *(the rail that makes 1/4/5 safe)*
- **From** evals as an optional folder → **to** evals as the *definition*; a pack can't reach
  `active` until its golden + adversarial cases pass *on the target warehouse*. AI-author writes
  evals **first**.
- **Why only aughor:** grounding lets evals assert *behaviour on real data*, not string matches.
- **Seam:** promotion gate `(pack, connection) → active iff evals green`, in CI + at bind time.
- **UI:** a pack "report card" — eval pass/fail per warehouse, blocking the activate button.
- **build·wire·test·leverage:** build the eval runner; wire to the activate gate; test a failing
  eval blocks activation; leverage = a regression in the engine flips a pack red before it ships.

### Bet 3 · The expert org — debate, escalation, a chief of staff
- **From** "route to N packs, fan out" → **to** a typed org: experts *disagree* about `revenue`
  and the conflict surfaces to a governed canonical; an expert *escalates* a billing-artifact
  finding to RevOps; a chief-of-staff meta-expert decomposes a board question and synthesizes.
- **Seam:** a typed inter-expert protocol (handoff / dispute / escalate) over the existing fan-out.
- **UI:** show the panel — who answered, who dissented, what was escalated.
- **build·wire·test·leverage:** build the protocol types; wire into the synthesis path; test a
  metric conflict routes to the canonical; leverage = a real cross-domain question shows a dissent.

### Bet 4 · A trust economy — autonomy is earned, not configured
- **From** "the kernel guarantees correctness" → **to** experts with a *measurable track record*
  (eval pass-rate, adversarial-survival rate, human-acceptance rate) that governs their rope.
  New/weak experts run **shadow** (propose-only); proven ones earn routing weight + autonomy.
- **Why only aughor / non-circular:** calibrated against captured human verdicts (§0.7), not self-grading.
- **Seam:** a per-`(pack, connection)` trust ledger → routing weight + autonomy tier.
- **UI:** an expert trust dashboard; per-finding "this expert is at tier N here".
- **build·wire·test·leverage:** build the ledger; wire human verdicts → score → routing; test a
  run of rejections demotes the expert; leverage = a demoted expert visibly loses autonomy.

### Bet 5 · Standing, goal-driven agents — headcount, not Q&A
- **From** an expert that answers when asked → **to** an expert with a *mandate + KPI* ("keep NRR
  > 110%; watch it; on drift, investigate, draft the fix, bring the receipt"), running on monitors,
  escalating only with decision-grade findings. Safe only once Bet 4 exists.
- **Seam:** a `mandate` block in `pack.yaml` (target + watch + escalation policy) → monitors.
- **UI:** a "standing agents" board — mandate, current KPI, last action, pending escalations.
- **build·wire·test·leverage:** build the mandate schema; wire to the Job Kernel/monitors; test a
  KPI breach triggers an investigation; leverage = an unattended drift produces a real escalation.

### Bet 6 · The marketplace — portable expertise as a network
- **From** a folder you write → **to** a tradeable asset: a world-class consultant encodes "the
  canonical SaaS Retention expert" once and it lights up on *anyone's* warehouse via the resolver.
- **Why only aughor:** everyone else's "expert" is a prompt that hallucinates on an unseen schema;
  ours is correct-by-construction (binds + re-evals locally before it can answer).
- **Seam:** pack as an installable, re-grounding, re-eval'd registry artifact (extend the metastore
  securable to cross-org import).
- **UI:** a pack marketplace — install, preview-on-my-warehouse, ratings, fork.
- **build·wire·test·leverage:** build import + re-ground + re-eval; wire to the activate gate; test
  an imported pack is disabled until it binds + passes evals; leverage = an imported pack answers
  correctly on a fresh warehouse.

### Bet 7 · Instruments — experts that bring more than SQL *(opportunistic)*
- **From** SQL-steering → **to** experts shipping governed analytical *tools* (survival model,
  forecaster, tuned anomaly detector) — declarative + capability-gated (mirror the Inference Plane's
  `vend_llm`), never arbitrary code.
- **UI:** an instrument shows its method + assumptions inline with the result.
- **build·wire·test·leverage:** build a capability contract; wire capability-gated invocation; test
  an ungranted instrument can't run; leverage = a retention answer uses a real survival model.

---

## Sequencing

- **Phase 0 (foundation, this arc starts it):** verification substrate — manifest + earned
  confidence + data-trust now; triangulation, adversarial refutation, human-verdict capture next.
  *Nothing else is safe until runs carry earned, non-circular trust.*
- **Phase A (compounding core):** Bet 2 evals-as-spec → Bet 1 flywheel, consuming *only verified runs*.
- **Phase B (safe autonomy):** Bet 4 trust economy → Bet 5 standing agents.
- **Phase C (leverage):** Bet 3 expert org → Bet 6 marketplace. Bet 7 rides along.

## Invariants
1. **The engine is unchanged by specialists** — they inject steering metadata at intake; executors
   and guards run identically (from v1).
2. **Nothing consumes a run above its earned trust** (§0.4) — the rule that keeps the flywheel safe.
3. **Trust is calibrated against external signal** (human verdicts + triangulation), never self-grading.
4. **Fail loud, never silent** — a skipped check is surfaced (defeats class E), never assumed.
5. **Confidence is computed with provenance**, never asserted by the LLM.

## Open risks
- **Self-learning drift** → fenced by Bet 2 (evals-as-spec is non-negotiable before Bet 1 ships).
- **Conflicting canonicals across experts** → governed metric wins; packs may *narrow*, never redefine.
- **Over-autonomy** → strictly gated by the trust tier × action reversibility; shadow by default.
- **Marketplace trust/security** → every imported pack re-grounds + re-evals locally; instruments capability-gated.
- **Verification cost** → manifest + scoring are cheap/static; triangulation + adversarial passes are
  gated to High findings only, so cost scales with stakes.
