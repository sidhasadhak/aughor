# The Ambiguity Ledger (SOMA improvisation I1) — resolution that compounds

*2026-07-06. Option B of the SOMA-leverage program (design:
[`SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md`](SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md)
§3/I1). Built after the B1 finding
([`SPIDER2_B1_PROBE_REPAIR_2026-07-06.md`](SPIDER2_B1_PROBE_REPAIR_2026-07-06.md)) showed the
residual accuracy lives in intent resolution, not inference-time machinery — which is exactly
what the ledger makes permanent.*

---

## 1 · The idea

SOMA re-pays its full probe pipeline every time any user asks an ambiguous question; the
resolution evaporates after the answer. Aughor has what a paper harness cannot — a persistent
per-connection substrate — so a resolved ambiguity can be **crystallized once and reused
forever**. SOMA's cost curve is flat per question; Aughor's **burns down monotonically per
connection** — the ambiguity space of a deployed schema shrinks with use. This is the mechanical
version of the "living context graph that compounds" (memory: `context-graph-closed-loop-gap`).

## 2 · What shipped

### The store — `aughor/semantic/ambiguity_ledger.py`
A first-class `AmbiguityResolution` record `{connection_id, schema_scope, dim(kind,facet,subject),
readings[], resolved_reading, resolved_sql, resolution_source(probe|user|verdict), evidence,
question_fingerprint, created, use_count}`, on a SQLite store built to the **house idiom**
(`resolve_db_path("AUGHOR_AMBIGUITY_LEDGER_DB", …)` + `tune` PRAGMAs + `run_migrations`), so the
suite never touches live `data/` (the registry-wipe scar — conftest override added). Key
properties, all unit-pinned:
- **Idempotent burn-down** — a deterministic natural key `(org, connection, facet,
  subject-fingerprint)` means re-resolving the same dimension collapses to **one row**.
- **Override-wins authority** — `verdict > user > probe`; a re-resolution only overwrites the
  reading when it arrives with ≥ authority, so **a probe can never clobber a human decision**.
- **Conservative retrieval** — token-overlap match (the `trusted_queries` idiom via
  `semantic/lexical.tokenize`), threshold-gated so an unrelated question injects nothing.
- `build_resolution_block` (authoritative prompt injection), `record_hit` (the served-count
  metric), `ledger_stats` (the burn-down chart: resolved-by-source vs served_total),
  `purge_connections` (catalog-delete cascade).

### The read path — `aughor/verify/priors.py` (product)
The ledger is now the **third plan-time prior**, alongside trusted queries and past corrections,
in the existing P1 closed-loop module — and it **leads** the block (an explicit resolution beats
an example). Injected everywhere `retrieve_priors`/`build_priors_section` is called, gated behind
the same `closed_loop` flag; zero prompt cost when nothing matches. A served resolution is counted
(the burn-down numerator).

### The write path + the loop — `evals/spider2.py` (`--ledger`)
When B1 settles a disagreement with executable evidence, `crystallize_resolution` writes it
(source `probe`, subject = the question so future similar questions match). The harness read path
injects any matching resolution as an authoritative prior before generation. This **closes the
compounding loop end-to-end** and is proven mechanically (no LLM) by
`test_compounding_loop_b1_settlement_then_read_back`, and **live** — a seeded resolution fired the
`ledger_read` step and injected into the real prompt on `local021` (db IPL).

### Tests
`tests/unit/test_ambiguity_ledger.py` (9: idempotency, override-wins, scoping, retrieval, stats,
purge, the end-to-end loop) + `tests/test_priors.py` (3 new: ledger reads back, flag-off zero-cost,
irrelevant-question empty). Ratchet-clean (swallows via `tolerate`), ruff-clean, **2320 unit tests
green**.

## 3 · Why this is the durable win

The B1 finding showed deterministic probing can't crack the residual grain-of-intent misses on
glm-5.2 — their resolver is a human/definition. The ledger converts that scarce, expensive
resolution (a probe that *does* settle, a user's clarify choice, a reviewer's verdict) into a
**permanent, per-connection, override-safe, receipt-ready** asset. Its value is amortization +
auditability, **immune to the benchmark noise floor** that killed two inference-time levers this
week. The `ledger_stats` chart — resolutions served from the ledger climbing while fresh
probes/asks fall — is the moat demo.

## 4 · Follow-on (I4 + I6, not yet built)

- **I4 · clarify fusion (product write path):** when a disagreement maps to AmbiIntent in `/ask`,
  surface ONE clarify chip whose options ARE the candidate readings with result previews; the
  user's choice writes to the ledger (source `user`). Seams mapped: `agent/soma.py`
  (`is_structural_suspect` / `generate_candidate_readings` / `assess_structural_ambiguity`, dark
  behind `AUGHOR_SOMA_CLARIFY`) + `agent/clarify.py` (live in `/ask`). The missing piece is
  capturing the user's *answer* to a clarify event and routing it to `save_resolution`.
- **I6 · receipt surfacing:** put `n_signatures` + the resolved dimension + probe evidence on the
  Trust Receipt ("this question admits 3 readings; this answer follows B because a live probe
  showed X").
- **Verdict → ledger bridge:** a `reject`/`correct` verdict that names a dimension crystallizes as
  a `verdict`-source resolution (the highest authority).
