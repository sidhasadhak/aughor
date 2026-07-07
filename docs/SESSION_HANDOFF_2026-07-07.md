# Session handoff — 2026-07-07 (SOMA leverage shipped · the accuracy fork is next)

*Read this first next session. Everything below is merged to `main`. Latest merged main =
`9d01de5`. Full unit suite **2336 green · ruff 0**; all new flags default-off. Nothing uncommitted.*

Supersedes [`SESSION_HANDOFF_2026-07-06.md`](SESSION_HANDOFF_2026-07-06.md).

---

## 0 · UPDATE — later on 2026-07-07 (three more PRs merged; start-here for next session)

Since the SOMA block below, **three more PRs merged to `main`** (carefully, in order, overlaps resolved locally):

- **PR [#114](https://github.com/sidhasadhak/aughor/pull/114) `8c87312` — retire `CanonicalMetric` from the compiler.** The last structured consumer now resolves the one `SemanticContract` via `resolve_planning_metrics` (behind `semantic.contract_live`, byte-identical off). REC-U10 tail done.
- **PR [#115](https://github.com/sidhasadhak/aughor/pull/115) `1275e94` — P-A + P-B parallel waves.** P-A = ADA WHY-lens wave (`ada.parallel_why_lenses`: interaction ∥ benchmark ∥ drill, byte-identical merge). P-B = `preflight.parallel` (plan_queries' 4 retrievals concurrent). Both default-off; wins are deterministic wall-clock (no endpoint A/B needed). **Live finding:** investigate-mode multi-hypothesis testing is DORMANT in the live graph — don't parallelize it.
- **PR [#116](https://github.com/sidhasadhak/aughor/pull/116) `9d01de5` — two Deep-Analysis bug fixes** found in a live run: (1) `LocalUploadConnection.make_reader()` clone crashed on every seed attach (missing seed-tombstone attrs) — fixed + retires a long-standing latent bug; (2) `_normalize_pct_key_numbers` corrupted `0.36pp`→`36.0%pp` (≤1→fraction ×100 mis-fire) — fixed with a pp-unit guard.

**Deeper WHY lenses — decision taken (with the user).** Live-verified on luxexperience: the deepen lenses add *genuine* value (the peer-benchmark busts the "size_fit is high for womenswear" premise → "it's high everywhere"; the drill proves it's systemic across 70 brands). **Kept default-OFF** (each adds an LLM query, ~2–3 min on a throttled endpoint; on converged data they just confirm "within noise"). New ROADMAP rework item: **confidence-triggered activation** — fire them only when the user needs more confident analysis (explicit "deepen" affordance / deterministic materiality trigger / [[reforce-agent]] confidence tiering); gate default-on-for-cross-sectional-why on that + the parallel-WHY wave capping latency.

**Next session — pick up here (in priority order):**
1. **The accuracy fork (§3 below) is still the headline** — a stronger inference endpoint is the one lever that moves Spider2. Needs the user's cost sign-off (parked, §4).
2. **P-C — refactor `run_analysis_phase` into a phase subgraph** (next in the parallel-waves program; see `docs/PARALLEL_MULTIAGENT_GROUNDWORK.md`). Deterministic, no endpoint needed.
3. **Confidence-triggered deeper-WHY-lens activation** (the rework item above) — design + build the trigger.
4. **Live wall-clock A/B** of the P-A/P-B/why-lens waves when endpoint time is available (correctness already proven; the wall-clock number isn't).
- Unchanged parked decisions (do NOT act without explicit go): the stronger-endpoint cost decision, the unsent Secure-Data-Share email, no Spider2 leaderboard submission — see §4.

---

## 1 · What shipped (the SOMA-leverage arc, on `main`)

The June/July measured conclusion — **cheap inference-time levers are exhausted on glm-5.2**
(±7–10-instance noise floor per full run, confirmed 4×) — pointed at exactly two moves the evidence
still supported. Both are now built, wired, tested, reviewed, merged.

| Piece | Where | What | Evidence |
|---|---|---|---|
| **B1 probe-and-repair** (eval) | `evals/spider2_probes.py`, `--probes` | SOMA's missing back half (I2+I3+I7): deterministic sqlglot AST-diff disagreement extraction → taxonomy triples, **zero model calls**; deterministic-first probe battery (reuses owned value/grain guards); evidence-typed `resolve()` behind **4 gates** — executes · clears-the-probe · no-regress (subject-granular) · AST-faithful → any fails ⇒ keep seed. **Monotonic by construction.** | 19 pure tests + live (5 instances, 0 regressions) |
| **The Ambiguity Ledger** (I1) | `aughor/semantic/ambiguity_ledger.py` | Resolutions crystallize per connection (house SQLite idiom): idempotent natural key = **one row per dimension** (burn-down), **override-wins** authority (verdict > user > probe). | 14 unit tests |
| **Read path** (I1) | `aughor/verify/priors.py::build_corrections_section` | The resolution block **leads** the plan-time prior on the **LIVE** answer paths (chat `investigations.py`, plan node `nodes.py`). #113 fixed the dead-wiring gap (it was only in `retrieve_priors`, which nothing live calls). | burn-down validated |
| **Write sources** (I4 + bridge) | `_stream_ask`, `record_verdict` | User clarify choice → `crystallize_user_choice` (source=user); reviewer verdict → `crystallize_verdict` (source=verdict, highest authority); B1 probes. | router + verdict tests |
| **I6 receipt** | `_write_answer_receipt` + `web/components/TrustReceipt.tsx` | Every answer records + renders any resolved ambiguity it applied ("followed a previously-resolved reading, settled by X"). | endpoint + capture tests |
| **soma previews** | `aughor/agent/soma.py` + `ChatPanel.tsx` | Clarify chips carry a result preview per reading (`= 68` vs `= 1131`) so the divergence is visible. | 8 soma tests |

Design specs (all current): [`SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md`](SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md)
· [`SPIDER2_B1_PROBE_REPAIR_2026-07-06.md`](SPIDER2_B1_PROBE_REPAIR_2026-07-06.md) ·
[`AMBIGUITY_LEDGER_2026-07-06.md`](AMBIGUITY_LEDGER_2026-07-06.md).

---

## 2 · The honest core (why this arc, and what it proved)

- **B1's finding:** on the 5 disagreeing Spider2 instances, every mechanism worked with **zero
  regressions**, but every miss was an `AmbiIntent` grain-of-intent the deterministic probes
  *structurally can't resolve* (the ambiguity lives inside an aggregation, invisible to a row-count
  probe), and there were **zero AmbiValue disagreements**. So the residual accuracy lives in
  **intent resolution** (human/definition), not inference-time machinery. This is what redirected
  the effort to the ledger.
- **The ledger's burn-down is validated** — through the *real* live seam (`build_corrections_section`,
  no LLM): 2 ambiguity classes resolved once (a user "by revenue" + a reviewer correction) → **served
  3× from the ledger with zero further asks**; `ledger_stats` served_total climbs while asks stay
  flat. The Option-B thesis holds: **cost curve burns down per connection.** (The token-overlap
  retrieval is conservative — it correctly *declined* a loosely-related question rather than
  mis-fire.)
- **The governing conclusion, unchanged:** the **one remaining accuracy lever is a stronger
  inference endpoint** (glm-5.2 caps ~56% Lite-local; oracle ~67% is base-model capability). The
  ledger converts scarce model capability into durable substrate — it complements a better model, it
  does not replace one. Cheap-lever whack-a-mole is done.

---

## 3 · Next session — the decision + the ready-to-build

**The fork (pick one):**

- **Option A — a stronger inference endpoint (the real accuracy lever).** Everything downstream is
  built and waiting. This is a *distribution-level* change: swap the coder model to a stronger one
  and re-measure Spider2 (the harness + guards + ledger all transfer). Blockers: which endpoint
  (Ollama Cloud throttles; a frontier API key would need the provider wired + the user's cost
  sign-off). This is the move most likely to move the number.
- **Option B — formally close B1 (the controlled measurement).** The gate B1 never got: same
  disagreeing subset, `--candidates 4` probes OFF vs ON, `--score` both, monotonic-or-it-dies.
  Prediction from the finding: on ≈ off (B1 keeps the seed on the AmbiIntent misses it can't
  resolve). ~endpoint-hours, throttled. Only worth it if you want the formal number before parking B1.
- **Option C — ledger polish (low priority).** Two specced follow-ons: (1) surface `n_signatures` +
  probe evidence on the receipt for **soma** turns — needs soma promoted to a first-class mode (it
  currently emits the clarify then returns, so there's no answer/receipt on that turn); (2)
  **consolidate the corrections store into the ledger** (today they coexist, deduped in
  `priors._dedup_resolutions_covered_by_corrections`). Neither moves accuracy.

**Recommendation:** **Option A.** The arc's own conclusion says the number now moves on model
capability, not engineering. Wire a stronger endpoint (with the user's cost go-ahead) and re-measure
— that's the honest next step. B (the formal B1 close) is a cheap tidy-up if you want the number
first; C is deferrable indefinitely.

---

## 4 · Standing decisions parked with the user (do NOT act without explicit go)

1. **A stronger endpoint needs a cost decision** — a frontier API key (billed) or a faster
   self-hosted model. Do not wire a paid provider without explicit approval.
2. **The Secure-Data-Share email** — DRAFTED at `docs/spider2-data-share-request-DRAFT.md`, never
   sent. Needs the Snowflake account id + explicit approval.
3. **Never** submit to the Spider2 leaderboard without explicit hard permission (memory:
   `never-send-without-permission`).

---

## 5 · Environment / gotchas (carry forward)

- **Model:** the runtime pins **glm-5.2:cloud** (`provider._cfg()['models']['coder']`), overriding
  `.env`'s `AUGHOR_CODER_MODEL`. Verify with `get_provider('coder')._model`, never the env var.
- **Endpoint:** Ollama Cloud throttles hard under sustained load (~5 inst/hr after several runs);
  iterate on the hard subset, full runs sparingly.
- **The ledger flags:** `closed_loop` gates the ledger read **and** the I4/verdict writes **and** the
  I6 receipt surfacing (all no-op when off — default off). `ask.clarify` (default ON) gates the
  clarify ask. `AUGHOR_SOMA_CLARIFY` (default off, **LLM cost** — one call per structural-suspect
  deep turn) gates soma structural clarify. Eval flags: `--probes` (B1), `--ledger` (harness ledger).
- **Reproduce the burn-down demo** (no LLM, proves compounding through the live seam): set
  `AUGHOR_CLOSED_LOOP=1` + scratch `AUGHOR_AMBIGUITY_LEDGER_DB`/`AUGHOR_VERDICTS_DB`, then drive
  `crystallize_user_choice` / `record_verdict` (writes) and `build_corrections_section` (the live
  read) and print `ledger_stats` per round. (The session's script lived in scratch; the seams are the
  contract.)
- **Spider2 clone:** `/Users/amitkamlapure/dev/Spider2` — `git pull` before campaign work; official
  `evaluate.py` needs the `warehouse` extra (`uv sync --all-extras`).
- **CI visibility:** the local `gh` PAT lacks `checks:read` — you **cannot** read individual CI check
  results via `gh pr checks`. Use `gh pr view <n> --json mergeStateStatus` — **CLEAN** = required
  checks passed, **UNSTABLE** = still running or a non-required check. Verify gates locally instead
  (`uv run pytest tests/unit`, `uvx ruff check`, `cd web && npx tsc --noEmit` + `npm run lint:tokens/format/elements`).
- **Codegen gate:** any change to a request/response pydantic model → regen `web/lib/api.gen.ts`
  (`cd web && npm run gen:api`) and commit it, or the `codegen` CI job fails.
- **Measurement discipline (unchanged):** controlled same-instance on/off + sentinels; never claim
  from a misses-only run; sub-10-instance deltas are noise on glm-5.2.
