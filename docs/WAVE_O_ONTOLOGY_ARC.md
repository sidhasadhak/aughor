# Wave O — Ontology parity + edge (scoping doc)

**Written before code, as C and V were**, because O touches five stores and the program's
own §4 says they must be mapped first. That instruction earned itself in Wave G: of seven
G items, the program's prose was **wrong or stale on four** — G2 was scoped "clearances
before roles" when roles already shipped enforced, G3 named counters that were the wrong
source, G1's premise held only under a flag that is off by default, and two items said to
"ride G1" turned out not to be small wiring at all. Every one of those was found by
reading the code first. This document is that reading, done up front.

**Plan of record:** [`PLATFORM_PROGRAM_2026-07-26.md`](PLATFORM_PROGRAM_2026-07-26.md) §4.
**Read with:** [`GENIE_DOCS_TEARDOWN_2026-07-26.md`](GENIE_DOCS_TEARDOWN_2026-07-26.md)
(the parity checklist) and [`WAVE_C_CONTEXT_GRAPH_ARC.md`](WAVE_C_CONTEXT_GRAPH_ARC.md)
(whose §"one graph per (org, connection, schema)" is the shape O2 generalises).

---

## 0. The five stores, as they actually are

Surveyed 2026-07-28 against the code, not the docs.

| Store | Persistence | Keyed by | Per-connection? |
|---|---|---|---|
| **ontology** | `data/ontology/` via `ontology/store.py` | `(connection_id, schema_name, fingerprint)` | ✅ yes |
| **overrides** | `data/ontology_overrides/{conn}/{schema}/{kind}/{id}.yaml` | conn + schema + kind + target | ✅ yes |
| **ambiguity ledger** | SQLite, `ambiguity_resolutions` | `(org_id, connection_id, dim_facet, fingerprint)` | ✅ yes |
| **glossary** | **one file** — `data/glossary.yaml` | term name | ❌ **global** |
| **metrics** | **one file** — `data/metrics.json` | metric name | ❌ **global** |

**O2's premise is confirmed, and it is exactly two stores.** Three of the five are already
connection-scoped. The debt `ontology/context_graph.py` names in its own docstring — *"the
fix for the two global-by-name stores (glossary, metrics), which are read-time-scoped to
the connection during projection"* — is real, and it is a read-time patch over a
write-time problem: the projection scopes them when building a graph, but the stores
themselves cannot hold two connections' different definitions of `revenue`.

This is the #198 shape stated in the program: **a store keyed without the dimension that
distinguishes its owners.** It has now bitten three times (the glossary exploration-writer
scope, the metrics catalog, and this) and the fix each time is the same.

**Synonyms do not exist as a store at all.** `tools/schema_linker.py` derives an ad-hoc
synonym expansion at query time from two sources — metric names and the connection KB's
title/tags — inside a `try/except` that logs at debug. There is no synonym record, no
source rank, no human authority, and nothing to review. O1 is therefore genuinely new
construction, not a re-key.

---

## 1. What each item actually has to do

Scoped against the survey above, with the program's intent preserved and its assumptions
corrected where the code disagrees.

### O1 — the vocabulary plane · ~2 PRs

Three sub-parts, and only the first is greenfield:

- **O1a — synonyms as a first-class store.** `(connection_id, subject_kind, subject_id,
  synonym, source_rank)` where rank is `human > mined > llm_candidate`. YAML under
  `data/`, git-reviewable, override-wins — the same discipline `ontology_overrides/`
  already practises, and the reason O7's round-trip is nearly free later.
  ⚠️ The existing `schema_linker` expansion must READ this store rather than being left
  beside it, or the platform gets two synonym dialects and Wave V's lesson repeats.
- **O1b — entity value dictionaries.** Profiler-fed low-cardinality value lists so
  "womenswear" resolves to a real column value. **Generated under a service context,
  never a user's** — Genie's own leakage carve-out, and now also a G5 concern: a value
  dictionary built from a table the reader lacks clearance for would leak its contents
  through the linker. **The G5 trim must apply here**, which is a dependency the program
  did not anticipate and this doc adds.
- **O1c — display name + typed format spec** per metric/property (currency, percent,
  decimals, compact). This is half of #189; the rendering half is S2 (J11). Declaring it
  without rendering it is deliberate and must not be "fixed" with a chart-level hack.

### O2 — re-key glossary + metrics · ~1–2 PRs

Global entries become `connection = "*"` defaults; scoped entries shadow them
(override-wins). **The migration is the whole risk**, and it has a known-bad precedent:
both files are live, tracked artifacts, and this repo has destroyed `data/` twice by
running non-hermetic writes. Therefore:

- Snapshot before, `git ls-files data/` after — the [[registry-not-test-isolated]] drill.
- Every existing entry migrates to `connection = "*"`, so **behaviour is unchanged until
  somebody scopes an entry**. A migration that silently narrowed an existing glossary to
  one connection would break every other connection's answers with no error anywhere.
- An isolation test: two connections, same metric name, different formulas, both resolve
  correctly. That test is the gate.

### O3 — retrieval ranking from usage · ~1 PR

Order candidates by ledger `record_hit`, drill records, trusted-query usage, V-freshness,
source rank. **Never edge evidence** (J4 stands; J14 restates it). One human YAML override
still beats any popularity score.

⚠️ **Pre-check before building, per the L3 lesson:** measure how many candidate lists in
the real corpus have >1 plausible candidate. If ranking changes the top pick on a small
fraction of questions, that is the finding, and it is cheaper to learn before the code
than after. The same check refused L3 and reshaped N3.

### O4 — the generalization loop · ~2 PRs

Mine accepted verdicts, trusted queries and (at onboarding) the source's saved/dbt/query-log
SQL into **typed candidates** (join / measure / filter / synonym / object-set) landing in
the **A4 resolve-once inbox** (J10 — one queue, no second store).
**Every candidate EXPLAIN-binds before it is offered**; unbound SQL is never shown.
Nothing auto-applies.

### O5 — window/semiadditive measures · ~1 PR

`order` / `range` (current·cumulative·trailing·leading·all) / `semiadditive: first|last` /
`offset` on `OntologyMetric`. "YoY growth", "trailing 7d", "balance at month end" become
*declared* measures the planner instantiates rather than per-query LLM SQL.
Gate: YoY eval cases pass with the measure declared and **fail honestly** without it.

### O6 — declared exclusions + drift checks · ~1 PR

Unmapped ≠ out-of-scope; per-connection coverage rollup. Scheduled cheap probes
re-validate declared cardinality/grain/active_filter, and a violated declaration flips the
edge `dirty` in **V's freshness vocabulary** (not a sixth dialect) and surfaces as a
caveat. This is the marketing line: Genie *documents* that a wrong cardinality promise
silently corrupts; Aughor **checks the promise**.

### O7 — interchange + connection-as-code · ~1 PR

OSI v1.0 YAML import/export; C6's pack becomes a **round-trip** through the *same* YAML
stores (J15 — a view over the stores, never a parallel format). Cheap only if O1a and O2
land YAML-shaped, which is why they are specified that way above.

---

## 2. Structural rules set before code

Stated now so they are not re-litigated per PR — the discipline Wave Q's doc uses for
"no second quality store".

- **J4 stands.** Ranking (O3) orders retrieval and never creates or weights an edge.
  Popularity is not evidence. Mined and LLM-proposed synonyms carry a source rank and are
  *candidates*, never authorities.
- **One queue.** O4's candidates land in the A4 inbox. A second suggestion store is the
  bug (J10, and the five-eval-surfaces lesson behind it).
- **One freshness vocabulary.** O6 speaks V's `fresh|dirty|stale|unknown`. Wave N3 already
  refused to add a fifth state and added an orthogonal axis instead; O6 does the same or
  says why.
- **One synonym reader.** `schema_linker` reads O1a's store; the ad-hoc expansion is
  replaced, not paralleled.
- **Override-wins everywhere.** A human YAML entry beats every generated, mined or ranked
  alternative, in all five stores.
- **G5 applies to new retrieval.** Any surface O adds that puts table-derived facts into a
  prompt goes through the clearance trim, including O1b's value dictionaries. New
  retrieval built after G5 that skips it silently re-opens what G5 closed.

## 3. Order and gates

**O2 → O1 → O5 → O3 → O6 → O4 → O7.** Re-keying first, because O1's synonyms and O5's
measures both want a per-connection home and building them global-then-migrating would
pay the migration twice.

Pre-registered gates (from the program §4, plus this doc's additions):

1. Two connections, same metric name, different formulas, both correct — **O2's isolation
   test, and the wave's headline gate.**
2. Synonym resolution measurably changes linker candidates with no pass-rate regression
   beyond the noise floor (O1 × E4 — floor before delta, J3).
3. A candidate failing EXPLAIN-bind is refused with its reason, tested (O4).
4. YoY cases pass with the window measure declared and fail honestly without it (O5).
5. An OSI file from Snowflake's examples imports to a usable ontology (O7).
6. **New:** a value dictionary built from a clearance-restricted table does not leak
   through the linker (O1b × G5).
7. **New:** `data/` verified clean after every migration step (`git ls-files data/`).

**Effort:** 7–9 PRs. O4 and O5 spend model requests; both run as scheduled batches inside
the free daily allowance (J3), and the grid rules apply — **ask whether the flag changes
the prompt before buying a grid.**
