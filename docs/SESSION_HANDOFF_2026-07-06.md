# Session handoff — 2026-07-06 (the 10x + Spider 2.0 program)

*Read this first next session. Branch: `2026-07-06-10x-program`, PR
[#111](https://github.com/sidhasadhak/aughor/pull/111). Everything below is committed + pushed;
suite 2606 green, ruff 0, tsc + 3 web gates green.*

---

## 1 · What shipped (proven, in the PR)

| WS | Status | What | Evidence |
|---|---|---|---|
| **WS4** hygiene | ✅ done | api.gen.ts regen 12,929→16,128 + offline `scripts/dump_openapi.py` + CI codegen gate · 4 bypass flags → `FLAG_ENV` · 47 silent swallows → `tolerate()` (ratchet 263→214) · FEATURES.md drift fixed | suite green each commit |
| **WS3** accuracy measurement | ✅ done | hermetic golden-replay CI gate (`tests/integration/test_golden_reference.py`, 53/53) — fixing it surfaced **9 tie-nondeterministic golden records + 2 scorer bugs** · guard fire/repair counters (`aughor.stats.bump`) · **live ratchet baseline 0.6551** pinned on glm-5.2 | `evals/README.md` protocol |
| **WS2** one SQL executor | ✅ done | `aughor/sql/executor.py` — shared pre-execute hardening (de-fan + preflight) wired into ALL 3 answer paths (explore + quick GAINED guards they lacked) + `test_guard_parity_all_three_paths_share_the_hardening` + import-boundary test. Post-execute repair loops left divergent **by design** (R3/KB/triangulation/B-7 are legit specialization) | +16 tests |
| **WS1** fast deep path | ◑ code done | `ada.parallel_phases` wave (`aughor/agent/phase_waves.py`) — baseline∥decompose∥dimensional concurrent, serial early-stop semantics post-hoc; 6 tests. **Live A/B: 373s→304s = 1.23× (NOT 2×)** — intake+synthesis dominate; profiling refuted the metric/ontology caches (not built). Flag default-off | AGENT_NOTES |
| **WS5-P0** Spider2 | ◑ harness done | `evals/spider2.py` rebuilt through the product pipeline; full 135 run = **72/135 = 53.3% on glm-5.2**; `scripts/spider2_fail_analysis.py` + `evals/spider2_diag.py` (show/run/triage) tooling | fail-analysis doc |

**Nothing merged yet** — PR #111 is open, awaiting review/merge decision.

---

## 2 · The measured accuracy story (the honest core)

Baseline 53.3% (glm-5.2, product prompt). Fail-analysis of the 63 misses: **wrong_values 49
(78%, grain-of-intent ambiguity), wrong_shape 8, empty 6, 0 exec-errors.**

**Every inference-time lever tried landed within measurement noise:**

| Lever | Built | Subset signal | Full-135 controlled | Verdict |
|---|---|---|---|---|
| Superset projection | `--bench-projection` | +12/63 (misses-only, artifact) | **net −2** | opt-in, negative |
| Column-semantics | `--col-semantics` | 0/2 on its own targets | not run | opt-in, unproven |
| A1–A3 harness fixes | empty-recovery wired · FK/PK context · SQL-only gen | +1/10, 0 regress | folded into candidates run | directional |
| Grain-of-intent guard | `aughor/sql/grain_intent.py` (12 tests) | — | — | monotonic-by-construction, kept |
| Candidates (Levers 4+5) | `--candidates K`, `evals/spider2_candidates.py` (6 tests) | +3/9, 0 regress | **71/134 = 53.0%, net −1** (9 recovered / 10 regressed) | opt-in, within noise |

**THE NOISE FLOOR (critical, in AGENT_NOTES):** ±7–10 instances of 135 churn between ANY two
full runs on glm-5.2 @ temp-0 (observed 3×). **No lever worth < ~+10 instances can be proven by
single runs here.** Reliability-banding (reps + McNemar) is the only honest instrument at this
effect size — ~5h/full-run, barely affordable. This is the **4th confirmation** of the June
meta-pattern: machinery perturbs a strong model's correct answers ≈ as often as it fixes wrong ones.

**What survives the noise argument** (the only moves worth endpoint-hours):
1. **Monotonic-by-construction mechanisms** — deterministic guards; evidence-gated repair that
   only edits with executable proof (this is exactly B1's design constraint).
2. **Distribution-level changes** — a stronger inference model; the substrate.
3. **Amortization plays** — the Ambiguity Ledger, whose value is compounding + auditable, not a
   single-run EX delta.

---

## 3 · Next session — the decision + the ready-to-build

**The design is fully specced:** [`SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md`](SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md)
(deep read of arXiv 2606.11424 verified mechanically + B1–B3 + 7 improvisations). Pick one:

- **Option A — B1 probe-and-repair (last inference-time experiment).** The one untested SOMA
  component AND the one that's monotonic by construction (can only edit what a live probe proves,
  gated by deterministic evidence-coverage checks). Design: spec §2/B1. Uses AST-diff disagreement
  extraction (`sqlglot`), a deterministic-first probe battery (we already own the AmbiValue/grain/
  date probes), ≤3 LLM probes on AmbiIntent residue. **~1–2 days.** Gate: controlled miss-subset +
  sentinels, monotonic or it dies (same protocol that killed 2 levers).
- **Option B — pivot to the Ambiguity Ledger (product, not benchmark).** The headline
  improvisation: probe/user/verdict resolutions crystallize into persistent per-connection
  `SemanticContract`s, so ambiguity burns down instead of recurring. Value is amortization +
  auditability, immune to the benchmark noise floor. Design: spec §3/I1+I4+I6. **~2–3 days.**
- **Option C — park WS5 until a better/faster inference endpoint exists.** The evidence says cheap
  levers are exhausted on glm-5.2; a stronger model is a distribution-level change that WOULD move
  the number. Everything is specced and waiting.

**Recommendation:** B1 first (it's the last honest inference-time experiment and its design is
noise-immune where the others weren't), then B (the ledger is the durable product win regardless
of benchmark). Avoid more cheap-lever whack-a-mole — 4 confirmations is enough.

---

## 4 · Standing decisions parked with the user (do NOT act without explicit go)

1. **Merge PR #111?** — or split the WS5 accuracy commits (13 of them) into a follow-up PR to keep
   #111 scoped to the 4 improvement workstreams. My rec: merge #111 as-is (WS5 is additive
   eval-only tooling, all flag-gated/opt-in), OR split if you want cleaner review boundaries.
2. **Send the Secure-Data-Share email?** — drafted locally (not in the repo),
   never sent. Needs your Snowflake account id (us-west-2) filled in + explicit approval.
3. **Never** submit to the Spider2 leaderboard without explicit hard permission (memory:
   `never-send-without-permission`).

---

## 5 · Environment / gotchas for next session (also in AGENT_NOTES)

- **Model:** the runtime config (`provider._cfg()['models']['coder']`) pins **glm-5.2:cloud**,
  overriding `.env`'s `AUGHOR_CODER_MODEL=qwen3-coder-next`. Verify with `get_provider('coder')._model`,
  never the env var. All this session's numbers are glm-5.2.
- **Endpoint:** Ollama Cloud throttles hard under sustained load (~5 inst/hr after several runs);
  iterate on the hard subset, full runs sparingly. `evals/spider2_diag.py run <id>` = 1-question loop.
- **Spider2 clone:** `/Users/amitkamlapure/dev/Spider2` — `git pull` before campaign work; the
  official `evaluate.py` needs the `warehouse` extra (`uv sync --all-extras`).
- **Run outputs** are gitignored (`evals/spider2_*`); `evals/spider2_out/` is the reference 53.3%
  run + `fail_analysis.json` that the diag/triage tools read — **preserved, do not delete.**
- **Measurement discipline:** controlled same-instance on/off + sentinels; never claim from a
  misses-only run (it can't see regressions); sub-10-instance deltas are noise here.
