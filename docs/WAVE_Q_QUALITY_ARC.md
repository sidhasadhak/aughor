# Wave Q — the Quality plane (scoping doc)

**Written before code**, as C, V and O were. Q's one structural rule is set here rather
than per-PR, because the program says so and because the survey below shows exactly how
easy it would be to break.

**Plan of record:** [`PLATFORM_PROGRAM_2026-07-26.md`](PLATFORM_PROGRAM_2026-07-26.md) §5.
**Read with:** [`WAVE_O_ONTOLOGY_ARC.md`](WAVE_O_ONTOLOGY_ARC.md) (O6 already produces
caveats; Q4 must not invent a second kind) and
[`WAVE_E_SESSIONS_EVALS_ARC.md`](WAVE_E_SESSIONS_EVALS_ARC.md) (the five-surfaces lesson
that J12 exists to prevent repeating).

---

## 0. J12 — "no second quality store" — and why it is the hard part

Surveyed 2026-07-28 against the code. Quality-shaped results are ALREADY recorded in
several places, none of which knows about the others:

| Surface | What it records | Where |
|---|---|---|
| **monitor alerts** | threshold / anomaly / drift / freshness firings, with severity, value, threshold, message | `monitors/store.py` → `monitor_alerts` table |
| **profiler** | per-column and per-table profiles (null ratios, distinct counts, min/max, semantic type) | `tools/profiler.py` → `profile_cache` |
| **trust checks** | deterministic result critiques (E1 function-semantics caveats) | `sql/trust_checks.py`, computed per answer, **not persisted** |
| **O6 declarations** | violated cardinality/grain/active_filter promises | `ontology/declarations.py`, computed per check run, **not persisted** |
| **eval suites** | pass/fail per case | `evals/store.py` (a different concern — do not merge) |

**The trap is precise.** Q1 introduces declarative *checks*, and a check result looks
exactly like a monitor alert: a table, a rule, a severity, a value, a time. Writing it to a
new `check_results` table would be correct-looking, easy, and would create the sixth
surface — the same shape Wave E found five times over for evals and Wave V found thirteen
times over for staleness.

**So the rule, stated before any code:**

> One results store. Monitors, checks and profiler-derived findings write the SAME table,
> keyed by `(connection, table, rule_id, run_id)`. `monitor_alerts` is the incumbent and
> the most likely home; if it cannot carry a check result without contortion, the
> **migration is part of Q3**, not an excuse for a second table.
>
> Eval results stay separate. They answer "is the platform right", not "is this data
> healthy" — merging them would be the opposite mistake.

A ratchet test proves monitors and checks share one store, mirroring the one G1 used for
declared-but-unenforced actions.

---

## 1. The items

### Q1 — the rule catalog · ~1 PR

Declarative checks per connection as YAML: `name`, `criticality` (`warn|error`), function +
args, optional filter, optional `for_each_column`. **Criticality is data, not code** — the
same check warns on one table and blocks on another.

**SHA-256 fingerprints per rule and per ruleset, with metadata EXCLUDED from the hash**
(DQX's trick, and the reason it matters here: editing a rule's note must not invalidate
every stored result computed under it, or nobody will ever annotate a rule).

~12 BI-trust checks compiled to source dialect through the existing sqlglot path:
`not_null`, `unique`/grain, FK integrity, `in_list`, `range`, freshness-vs-SLA, row-count
drift, accepted-values drift.

⚠️ **Pre-check before building the compiler:** confirm the sqlglot path can already emit
per-dialect predicates, rather than assuming it. O3's pre-check and G's four wrong premises
are the argument.

### Q2 — profile → candidates → review · ~1 PR

Profiler thresholds (null_ratio, distinct ratio, min/max) emit **deterministic** candidates
into the **A4 resolve-once inbox** — the same queue O4 uses (J10). LLM proposals are allowed
as *additional* candidates, syntax-validated, never auto-applied.

**Reuse O4's `Candidate`**, do not re-declare one. Q's candidates are a different `kind`,
not a different type; a second candidate model is a second queue with extra steps.

### Q3 — persisted results, one store · ~1–2 PRs

Per-table pass/fail counts + `run_id` + ruleset fingerprint. Monitors' outputs unify into
it. Graph table-nodes gain health provenance. Results are **V-freshness citizens**: a stale
health verdict is itself `stale`, never silently authoritative.

The `run_id` spine ties artifact ↔ metrics ↔ ruleset version.

### Q4 — caveats ride the answer · ~1 PR — **the first-mover feature**

Tables in the executed SQL join against latest health results at answer time; failures
within severity/age thresholds render inline with provenance —
*"`orders` failed freshness 2 days ago (expected daily; last row 2026-07-23)."*
`warn` annotates; `error` can gate V3 publish.

⚠️ **O6 already produces caveat strings** for violated declarations, and `trust_checks`
produces them for result semantics. Q4 must RENDER all three through one path, not add a
third. A caveat the user sees twice in different words is a caveat they stop reading.

---

## 2. Structural rules set before code

- **J12 — one results store.** Stated above; ratchet-tested.
- **J10 — one review queue.** Q2's candidates land in the A4 inbox beside O4's.
- **One caveat path.** Q4 renders O6's, `trust_checks`', and Q3's through a single
  assembler with one dedup rule.
- **V's freshness vocabulary.** A health verdict ages; it speaks `fresh|dirty|stale|
  unknown` and adds no fifth state (N3 refused one, O6 refused one).
- **Deterministic first.** Every check is deterministic; LLM proposals are candidates only,
  and never a check itself. A quality plane whose verdicts a model authored cannot be the
  thing that gates a publish.
- **Fingerprint excludes metadata.** Annotating a rule must not invalidate history.

## 3. Order and gates

**Q1 → Q3 → Q2 → Q4.** The store lands before the producers that feed it, so the second
producer (Q2) has somewhere to write and no one is tempted to add a table.

Pre-registered gates:

1. Editing a rule's note does not change its fingerprint (test).
2. A ratchet proves monitors and checks share one results store.
3. An answer over a failing-freshness table renders the caveat with rule name + run id.
4. An `error`-criticality failure blocks publish with the reason and an override path.
5. **New:** a caveat that O6 and Q3 both produce renders ONCE.
6. **New:** `data/` verified clean after any migration step (`git ls-files data/`).

**Effort:** 4–5 PRs. Deterministic throughout — zero model quota.
