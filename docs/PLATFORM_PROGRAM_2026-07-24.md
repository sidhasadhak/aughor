# Aughor Platform Program — the unified wave roadmap (2026-07-24)

**This is the forward plan of record.** It merges the Foundry study's six-wave roadmap
([`PALANTIR_FOUNDRY_STUDY_2026-07-22.md`](PALANTIR_FOUNDRY_STUDY_2026-07-22.md) §5) with the
five-repo study's adoption tiers ([`FIVE_REPO_STUDY_2026-07-23.md`](FIVE_REPO_STUDY_2026-07-23.md)
§3/§5) and the actual build state. **It supersedes both of those documents' sequencing sections**;
they remain the scoping authority for the content inside each wave. `ROADMAP.md` §0 remains the
session-level status page and should point here.

**How the two sources compose.** The Foundry study set the *destination* (the all-inclusive
platform: kinetic loop, trust flywheel, automations, artifact lifecycle, governance, surface). The
five-repo study is a *field report from five teams who shipped* — and it changed the plan in two
ways rather than adding a parallel list:

1. **The trust plane must extend into the LLM transport itself.** Request-level reliability,
   provider-plane guards, and binding-fidelity evals are guard-battery work — same philosophy, new
   plane. All five repos converged on determinism-as-authority; the competitive question is no
   longer *whether* guards, but *which planes* have them. Aughor's transport plane is currently the
   least guarded (the #197–#202 arc fixed incidents; this makes the fixes structural).
2. **The context plane needs its read-back artifact.** Aughor captures context (glossary, ledger,
   dossiers, profiles) but nothing reads it back as one authority at question time — the open
   feedback-loop finding. Understand-Anything's 75k stars are the existence proof that a committed,
   versioned, deterministically-refreshed graph *artifact* every question passes through first is a
   product mechanic, not plumbing.

So two waves are added (**R** — Reliability, **C** — Context graph), three tier-2 items are folded
*into* Wave A where they redesign it (not bolted after it), and T3.2 becomes Wave E4's methodology.

---

## 1. Where the build actually is

| Wave | State | Evidence |
|---|---|---|
| **K — Kinetic plane** | ✅ **COMPLETE** ([#201](https://github.com/sidhasadhak/aughor/pull/201)) | K1–K5 merged; follow-ons dispositioned in §5 below |
| **A — Automations** | ✅ **BUILT (A1–A6)** — A1+A2 [#204](https://github.com/sidhasadhak/aughor/pull/204), A3 [#206](https://github.com/sidhasadhak/aughor/pull/206), A4 [#207](https://github.com/sidhasadhak/aughor/pull/207) merged; **A5 [#208](https://github.com/sidhasadhak/aughor/pull/208) and A6 await merge authorization** | Arc: [`WAVE_A_AUTOMATIONS_ARC.md`](WAVE_A_AUTOMATIONS_ARC.md) |
| **E — Sessions + Evals** | ◐ **HALF DONE** — E1–E3 merged (#196); E4–E6 remain | Arc: [`WAVE_E_SESSIONS_EVALS_ARC.md`](WAVE_E_SESSIONS_EVALS_ARC.md) |
| **R — Reliability (transport)** | ✅ **BUILT (R1–R5)** — local commits `ff76b08` · `18ebb52` · `79106dc` · `9fa2c4d` · `1d78cd6` · `ba524be` · `60b9fb0`, **none pushed** | Scope: five-repo study §3 T1.1–T1.3 (+T2.3/T2.4/T2.5); status in `ROADMAP.md` §0 |
| **C — Context graph** | ⭕ not started — *new wave, from five-repo T3.1* | Needs its own scoping doc before code |
| **V — Artifact lifecycle** | ⭕ not started | Foundry §5, now ⊕ UA's freshness/committed-artifact mechanics |
| **G — Governance uplift** | ⭕ not started | Foundry §5, now ⊕ K's 9 unenforced `_RISK` actions ⊕ grant surfacing |
| **S — Surface & composition** | ⭕ not started | Foundry §5, now cheaper by one wave (entity pages render C's graph) |

Open PRs to land first: [#203](https://github.com/sidhasadhak/aughor/pull/203) (reduce.py retirement
+ ROADMAP §0) and [#204](https://github.com/sidhasadhak/aughor/pull/204) (Wave A1+A2).

---

## 2. The program — one sequence

```
        #203 · #204 land
              │
   ┌──────────▼──────────┐
   │  A (finish: A3–A6)  │   A4 is REDESIGNED by openworker (see §3, J1/J2)
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │  R  (transport)     │   deterministic; zero quota to build; de-risks every wave below
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │  E (finish: E4–E6)  │   E4 runs on REFRACT methodology (J3); measures the 5 unproven flags
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │  C  (context graph) │   scoping doc first; closes the read-back loop (J4); the product bet
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │  V  (artifacts)     │   versions/freshness generalized — C's graph is its first-class citizen (J5)
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │  G  (governance)    │   tags/clearances/attribution ⊕ the 9 _RISK enforcements ⊕ grant surface
   └──────────┬──────────┘
   ┌──────────▼──────────┐
   │  S  (surface)       │   entity pages = C's graph rendered (J6); verbs; module interfaces
   └─────────────────────┘
```

**Mainline: A → R → E → C → V → G → S.**

### Wave A — finish (A3–A6), redesigned at A4

- **A3 — source version probes.** Cheap per-(connection, table) version (`MAX(pk)` / `MAX(ts)` /
  count+ts fingerprint), the `source_change` condition. Generalizes the explorer watermark's *shape*
  without touching its scan behaviour. Deterministic.
- **A4 — staged proposals ⊕ the resolve-once inbox ⊕ standing grants.** *Changed by the five-repo
  study — see J1/J2.* This is no longer "persist K4's Proposal dataclass"; it is the
  pending-interaction plane, built to openworker's semantics.
- **A5 — adopt monitors + briefs onto the engine** behind `automations.adopt_legacy`, legacy
  schedulers intact, equivalence tests (same alert severity/message/debounce). A5's *unattended*
  safety story is J1's inbox + grants.
- **A6 — surface.** Author conditions/effects, run history with the reason a tick did nothing,
  mute/pause/expire, work the proposal queue. Pairs with Wave S momentum.

### Wave R — Reliability: the transport plane (new)

The five-repo Tier 1, plus the three answer-path items that ride along. **Entirely deterministic to
build** (fakes for every provider behaviour), directly attacks the request budget, and closes three
already-paid-for bug classes *structurally* (guessed model ids · fast-tier pin clobber · health
check covering one model). Scope authority: five-repo study §3.

> **Built 2026-07-24 (local, unpushed): R1 `ff76b08` · R2 `18ebb52`.** Building them measured the
> transport stack end-to-end and found two leaks nobody had priced. **Instructor's default is three
> attempts and we had never overridden it** — every structured failure re-sent the whole prompt three
> times before our code saw the error, and the fallback chain then spent a fourth on another
> provider. And **a validation error was buying a "the shim rejected the reasoning extras" retry**,
> because that degrade's guard admitted anything neither transient nor quota-blocked. Both fixed;
> measured before→after, five failure classes went from *3 requests, failed* to *1 request,
> succeeded*. J8 is now satisfiable — `llm.salvage.*`, `llm.failure.*`, `llm.repair.*` and
> `llm.gate.*` land in `GET /dev/stats`, so R's cost claims can cite measurement.
>
> One scoping note carried forward: **the vouched matrix cannot block an unvouched id.** The picker
> is deliberately free text (a stale catalogue must never block a model someone is paying for), so
> the matrix holds *our own shipped defaults* to the higher bar — absent from the matrix ⇒ CI fails —
> and merely warns on a user's pin. That is the honest version of "bindings resolve through it".

- **R1 (=T1.1) — shared reliability layer for structured LLM calls**: deterministic normalizer
  *before* any repair call (fence-strip, trailing-comma, enum nearest-match, extra-key drop) ·
  classify-before-retry with a canonical failure taxonomy (a retry cannot fix a truncation) · ONE
  bounded repair carrying the specific validation error, token-capped · line-oriented micro-formats
  for the tightest contracts · a deterministic gate in front of every *optional* LLM call, with a
  "skipped by gate" counter.
- **R2 (=T1.2) — provider-plane hardening**: error-body-marker classification in the failover chain
  (quota-exhausted markers → skip provider for the day; `model_not_found` → **loud config error,
  never failover** — silent failover masks guessed ids; plain 429 → existing cooldown) · a vouched,
  date-stamped model matrix that **per-agent bindings must resolve through** · per-provider
  cheapest-call health check that distinguishes bad-key / wrong-endpoint / unreachable ·
  fix-what-the-server-named one-shot param retry · the Gemini schema-allowlist and Anthropic
  streamed-usage quirk encodings diffed against our paths.
> **R3 built 2026-07-24 (local): `79106dc` + `9fa2c4d`.** All three items, six flags, all off by
> default. Measured on real inputs: the two-tier catalog cut the repair prompt **65%** on the real
> 57-table workspace schema; evidence stubbing cut a realistic synthesis block **57%**. Two scoping
> notes worth carrying: the wandering detector's *churn* and *no-progress* signals each catch a
> failure the other two counters structurally cannot, which is why all three exist rather than one;
> and **`ada.evidence_stubs` is the one Wave-R flag with a measurement debt** — it drops rows a
> narrator could cite, so it must not graduate until **E4** can A/B it. That is a concrete customer
> for E4 on top of the five the flag-graduation audit already named.

- **R3 (=T1.3) — context-budget discipline for ADA**: fresh-full/stale-stub evidence rendering
  (grounded numbers re-fetched by id, never re-generated — sibling of #202's condensation) ·
  two-tier schema catalog with error-path autoload · the wandering detector (args-hash repeat →
  notice → pre-dispatch veto → graceful termination; plus distinct-args churn detection).
> **R4 built 2026-07-24 (local): `1d78cd6` + `ba524be`.** The finding that shaped it: the `error`
> SSE frame was hand-assembled at **fifteen** sites, so the classification R1 and R2 built reached
> nobody. One function owns the shape now, and a test forbids inline assembly — the T2.4
> choke-point principle applied to the outbound error path. The anti-probing half needed **no fix**:
> the rule already held everywhere, so it became a ratchet instead. Two boundaries are pinned with
> it, because the rule is easy to over-read — the TRUE row count is still reported (honest coverage
> prevents an over-claim; it is not a suppression signal), and a policy-blocked query still says so
> (silently returning zero rows would make a permissions failure look like a finding of absence).

- **R4 (=T2.3+T2.4) — answer-path hardening**: no-orphan interrupt/retry on streamed `/ask` (typed
  error tail; "switch model, then retry" is the blessed recovery) · `_display` sidecar with ONE
  tested outbound choke point; guard-suppressed data indistinguishable from absence in the model's
  view, surfaced to the user out-of-band.
- **R5 (=T2.5) — declared parallel-safety** as a uniform metadata property on tools/actions, checked
  in one place (the SQL gate already enforces the read side; this names it as the action surface
  grows).

> **R5 built 2026-07-24 (local): `60b9fb0` — Wave R is COMPLETE.** The design decision worth
> carrying: the check sits on the **dangerous** side, not the fan-out side. A concurrent region
> declares itself; the K-plane executor asks, once. A guard every fan-out must remember to call is
> the shape that already failed twice here (the ~5-site guard battery; R4's 15 error frames), and it
> fails silently — a fix lands in one copy while the rest diverge. Inverting it means a fan-out added
> next year is covered without touching the safety module. The ratchet test that enforces "every
> `ContextThreadPoolExecutor` declares its region" found a **seventh** fan-out during the build,
> in a file the author's grep had never opened.

### Wave E — finish (E4–E6), with T3.2 as E4's methodology

- **E4 — per-run overrides / grid experiments ⊕ the fidelity harness (J3).** The flag override must
  wrap `build_graph_generic` (topology flags read at COMPILE time); `set_run_model()` exists.
  E4 finally has both a **customer** (the 5 flags the graduation audit could not measure) and a
  **methodology** (REFRACT: floor verification, repeatability, harmonic composite, perturbation
  axis). The P7 "frontier bakeoff" re-opens here as a product feature, not a session errand.
- **E5 — the Evals surface** (frontend recipe already written in the arc doc).
- **E6 — "add this run as a test case" + the promotion gate** (generalizing `packs/evalgate`).

### Wave C — the connection knowledge graph (new; the product bet)

One typed, committed, versioned graph artifact per connection — tables, metrics, glossary terms,
domains, findings, briefs as nodes; joins/defines/derived-from/grounded-in/resolves as edges —
deterministic layer from schema + dbt + profiler + **guard evidence**, LLM for summaries only.
Three-level anti-hairball rendering, a computed connection tour, the **grep-the-graph-first answer
protocol** (the concrete fix for context-captured-but-never-read-back), typed freshness states with
token-proportional refresh, and the committed-artifact + skills-pack distribution mechanic.
**Scoping doc first, Foundry-study style — it unifies five existing stores (glossary, ledger,
dossiers, TOUR, Qdrant) and must be mapped before code.** Build it as a real program (J4), never a
pipeline-as-prompt.

### Waves V → G → S — as scoped in the Foundry study, with the fold-ins

- **V** absorbs UA's mechanics: typed staleness states (fresh/dirty/stale/unknown), a
  change-classifier decision matrix for rebuilds, save≠publish + freeze + changelog — and C's graph
  is its first-class versioned citizen (J5).
- **G** absorbs the K follow-on (wire `govern.guard` into the **9 pre-existing unenforced `_RISK`
  actions**), the grant listing/revocation surface in the trust receipt, tag plane + clearances
  before roles, audit categories with the LLM call as a first-class event, usage attribution.
- **S** gets entity pages nearly free as a rendering of C's graph (J6), plus next-action verbs,
  typed module interfaces, the capability matrix, packs-as-products.

---

## 3. The joints — where integration changed a design (not just an ordering)

- **J1 — A4 is the resolve-once inbox, not a proposal table.** One store for staged proposals AND
  pending interactions: items resolve **exactly once** (first-responder-wins; second resolution is a
  no-op), keyed idempotently by `(run_id, call_id)`, durable — a restart rebuilds suspensions from
  the transcript and finds already-resolved items without re-prompting. *Unattended mode changes
  where the human is reached, not the autonomy ceiling.* This **closes and supersedes** the K5
  follow-on "persisted proposal queue".
- **J2 — Accepting can mint a target-bound standing grant.** Never "allow `refund_orders`" — always
  "allow `refund_orders` → `<exact target string>`", eligible only when the action declares a single
  target argument, never for exec-class, **owned by the automation that minted it** (revocation is
  per-owner; deleting the automation takes its grants along), re-read on every check, and every
  auto-allowed run cites its grant in the audit log and receipt. This is the graduated-autonomy
  upgrade that makes A5's adopted monitors/briefs safe unattended.
- **J3 — E4 refuses to attribute what it cannot floor-verify.** Reference-vs-reference first; if the
  same binding disagrees with itself beyond threshold, deltas are refused (mechanizing "replicate
  before trusting deltas at small n"). Repeatability stdev per axis; harmonic-mean composite (one
  broken axis fails loudly) + plain-English diagnosis; a perturbation-brittleness axis with
  Aughor's *deterministic* comparators (same result set ⇒ zero drift — cleaner than REFRACT's own);
  fixture fingerprints (#198) stamped into every report; a one-time proxy-inversion audit of
  existing metrics. Runs as a **scheduled batch inside the free 1,000 req/day**, never inline.
- **J4 — C's edges carry real provenance or don't exist.** Join edges annotated with the join
  guard's *measured* value-domain overlap % — auditable confidence where UA hardcodes weights. The
  builder is a real program calling the LLM for narrow emissions (their pipeline-as-prompt scars are
  the warning), and graph search wires to Qdrant on day one (their BUILT-not-WIRED miss becomes our
  first delivered query).
- **J5 — V generalizes C's freshness rather than inventing its own.** One staleness vocabulary
  (fresh/dirty/stale/unknown) and one change-classifier shape serve graph, briefs, profiles, and
  exploration caches alike; "live-by-default + explicit freeze" applies to the graph artifact the
  same as to a chart.
- **J6 — S renders C.** An entity page is C's node + dossier edges + past findings; the Foundry
  study's "zero-config entity pages" line item stops being a build and becomes a view.
- **J7 — R is where transport incidents become structure.** The vouched matrix bindings must resolve
  through kills "guessed model ids" and "pin clobbered the fast tier" by construction; marker-based
  error classification extends the "Google's quotaId is the authority" lesson chain-wide; the
  health check stops covering only the coder model.
- **J8 — R ends arithmetic-only cost claims.** R1's counters ("repair calls saved", "skipped by
  gate") and the failure taxonomy land in `obs.session_log` rows — standing item §0.6 (measure LLM
  spend from our OWN log) is satisfied *by* Wave R's decision gates, which must cite measured
  before/after, not call-count arithmetic.

---

## 4. Why this order (and the named alternates)

1. **A finishes first** because it is in flight (momentum, an open PR, an arc doc with met gates)
   and because A4's redesign (J1/J2) is the substrate R4's interrupt/resume and G's grant surface
   assume exists. A3–A6 need essentially no quota.
2. **R before E** because E4's harness *spends requests* — building the transport guards first makes
   every E4 batch cheaper and more classifiable, and R needs zero quota to build (all provider
   behaviour is faked in tests). R also hardens the exact plane every later model-heavy wave leans
   on. *Alternate:* if flag-graduation urgency wins, E4 can run first on raw transport — nothing in
   E4 hard-depends on R.
3. **E before C** because C is the largest new surface and deserves its scoping doc while E4's
   harness starts producing measured evidence; also C's LLM emissions (summaries, tour narration)
   benefit from R+E4 (reliable calls, measurable quality). *Alternate:* product-differentiation-first
   promotes C directly after R; the scoping doc can be written during E regardless — it has no code
   dependency.
4. **V after C** so versioning/freshness generalizes something that exists (J5) instead of being
   built speculative. **G is orthogonal** and can interleave anywhere after A (its inputs — the 9
   `_RISK` actions, grants, audit categories — all exist by then). **S last** because it composes
   everything and is cheapest once C exists (J6).

---

## 5. Standing items — preserved, with their new homes

| Item (ROADMAP §0) | Disposition |
|---|---|
| Flag graduation Batches 2+ — 5 flags E4 must measure | **Wave E4** (its first customer); the other dispositions stand |
| `ask.brief_context` + `ask.conversation_context` soak | Standalone, anytime a live server is up; not wave-blocked |
| Measure LLM spend from our OWN log (`session_events` = 0 rows) | **Wave R** (J8) — R's gates require it |
| Sub-1 shares render `0.275985` not `27.6%` (#189) | **Wave S** (presentation semantics decided there) |
| Retire the 7 stale rejects in `exploration_workspace.json` | Standalone chore; needs live column types |
| P7 frontier tier | Decided (keep `glm-5.2:cloud`); **re-opens inside E4** as grid experiments |
| Platform WP-5/8/9/12–16 | Fold at wave boundaries (WP-7 metering already carries A's heartbeat; WP-8/9 are G-adjacent; keep the list in `PLATFORM_REVIEW_AND_IMPLEMENTATION_PROGRAM_2026-07-12.md`) |
| K2b — `query`-kind dispatch through the read-only executor | Small; ride with any K-plane session (A5 or G) |
| K5 polish — persisted proposal queue | **Superseded by A4** (J1) |
| K5 polish — inline "annotate this cell" affordance | **Wave S** |
| `trigger_investigation` seam (K2 still raises) | Task chip filed (`task_401e3882`): lift A2's runner into a neutral module; both executors call it |
| 9 unenforced `_RISK` actions | **Wave G** (unchanged) |
| Ontology-overrides root has no env override | Task chip filed (`task_275035a4`): hermeticity gap, same class as the two data-loss incidents |

---

## 6. Rules of engagement (every wave, non-negotiable)

1. **Default-off flags, byte-identical when off.** Every wave ships gated; `main` must not change
   behaviour until a flag flips. (K and A both held this.)
2. **Pre-registered decision gates per PR.** Stated before building; if a gate can't be met, the PR
   is wrong, not the gate.
3. **Prove it on the live path before saying done.** Green tests are necessary, never sufficient —
   this program's own history: K3/K4's mocked-org and swallowed-401 bugs, and A2's 48-second retry
   burn + wrong-diagnosis message, were ALL invisible to hermetic tests and found by the live proof.
4. **Snapshot `data/` before any full-suite run; diff after.** Two real data-loss incidents stand
   behind this rule.
5. **Push once per branch; CI is advisory; local gate = `uvx ruff@0.15.20 check .` + targeted
   tests; let the full suite run once before merge.**
6. **Strictly `:free` model bindings.** The OpenRouter credit is a threshold-unlock reserve
   (1,000 req/day), never a spend budget; Gemini billing stays OFF (it deletes the free tier).
   Model-heavy gates (K4-style live proofs, E4 batches) budget requests explicitly.
7. **The anti-patterns table is binding** ([`FIVE_REPO_STUDY_2026-07-23.md`](FIVE_REPO_STUDY_2026-07-23.md) §4):
   no aisuite dependency, no pipeline-as-prompt orchestration, no hand-written connector monoliths,
   no prefix-match allowlists, **no read-by-default risk fallback** (undeclared ⇒ blocked), no
   convention-based provider discovery, no provenance-free LLM edges, no coercive hook injection.
8. **An unused param is worse than a missing one; ratchet the call site, not the function; a delete
   is durable only when intent (tombstone) is the authority.** The recurring bug shapes this
   codebase has already paid for — new waves don't get to pay for them again.
