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

## 4 · I4 (clarify write path) + I6 (receipt) — shipped

### I4 · the user's clarify choice writes to the ledger
The missing half of the loop: capturing the user's *answer* to a clarify. When a `/ask` turn
answers a clarify, the chosen reading rides back on the request and crystallizes as a
`user`-source resolution (the highest autonomous authority — only a reviewer verdict outranks it):
- `aughor/semantic/ambiguity_ledger.py::crystallize_user_choice` — maps the clarify kind to the
  taxonomy (a term choice → AmbiValue, an interpretation → AmbiIntent), writes source `user`.
- `AskRequest` gains `clarify_reading` / `clarify_subject` / `clarify_source`; `_stream_ask`
  crystallizes **before** answering (gated `closed_loop`), so the resolution is a prior on this
  very turn and every future one.
- Frontend: the clarify card's re-ask (`web/lib/useChat.ts` + `web/components/ChatPanel.tsx`)
  carries the chosen chip text back.
- This works on the **live deterministic clarify path** (`clarify.py`), not just the dark soma
  path — so "urgent orders" → the user's status choice burns down that term ambiguity too.
- Tests: unit (`crystallize_user_choice`, override-wins vs a probe) + **live through the real
  router** (`test_ask_router.py` drives `/ask` with a clarify answer and asserts the ledger write).

### I6 · the Trust Receipt surfaces ambiguity handling
`_write_answer_receipt` now records, for every answer, any Ambiguity-Ledger resolution the
question matched — a `resolved_ambiguities` payload field + a `resolved_ambiguity` lineage edge —
so "this answer followed a previously-resolved reading (settled by a probe / the user / a
reviewer)" is inspectable. One site covers chat + ADA + partial. Gated `closed_loop`; tested by
capturing the receipt payload.

### Lifecycle
The connection-delete cascade drops a connection's resolutions (`bootstrap._ambiguity_conn` purge
hook + a case in `test_connection_purge.py`) — per-connection burn-down state dies with the
connection.

## 5 · Remaining follow-on

- **Render the receipt field** — I6 writes `resolved_ambiguities` to the receipt payload; a UI
  panel to *show* it on the Trust-Receipt surface is the natural frontend follow-on.
- **Light up the soma path** (`AUGHOR_SOMA_CLARIFY`) so structural disagreement (candidate
  readings with result previews) drives clarify chips in the product — then I4 captures those too,
  and `n_signatures` + probe evidence join the receipt.
- **Verdict → ledger bridge:** a `reject`/`correct` verdict that names a dimension crystallizes as
  a `verdict`-source resolution (the highest authority).
