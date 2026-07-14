# Ground-first answer resolution (2026-07-13)

*Status: BUILT + real-data-validated, behind flag `ask.resolve_first` (default OFF). Branch
`ground-first-resolution` (3 commits off `main`, NOT pushed, NO PR). This doc is the self-contained
handoff — a new session can resume from it.*

## Why (the problem)

Repeated live-app failures on **"Show me month-wise sales for Mytheresa"** traced to one architectural
cause: **Aughor answers first and validates later.** The quick chat path (`_stream_chat`) assembles
grounding as prompt *context*, lets the LLM write SQL under only *soft* prose constraints (so it silently
downgrades `monthly`→`fiscal_year`, or runs an empty `franchise='Mytheresa'` filter), then runs **~9
deterministic guards + 2 LLM passes** (the `SqlWriter.fix` loop and the semantic `inspect`) that each
*re-decide* entity/grain/measure and **contradict each other** — the "massive disconnect" (inspect invents
a `fiscal_month` column; the narrator says monthly is unavailable; the follow-ups doubt it; the
empty-narrative fallback sums annual figures into a nonsense total).

A competent analyst does the opposite: **resolve the entity → locate the measure at the requested grain →
reconcile ONCE → answer.** One grounded decision, made *before* querying, that the whole answer renders.

## The principle

One deterministic resolution runs **before** generation, **constrains** it, and **speaks through** the whole
answer — and it lets us **DELETE** post-hoc guards rather than add a sixth. "Fewer, load-bearing constraints."

## What's built

**`aughor/semantic/answer_resolution.py`** — `resolve(question, *, schema, db, connection_id, eff_schema)
-> Resolution` (deterministic, never raises; degrades to `answerable`). **Measure-first** (this is the
load-bearing correction — see the real-data bug below): resolve WHAT the question is about (the measure
noun → column synonyms), compute the tables that carry it, then bind the entity and read the grain from
ONLY those tables.
- **Entity** — from the schema's value annotations (`-- [Mytheresa, …]`, written by
  `tools/schema.py::inject_value_annotations`) + `ValueIndex` fuzzy; prefers a measure-bearing table
  (`_pick`). A bounded, `''`-escaped, read-only DB existence probe (`_db_find_value`, label `__resolve__`,
  ≤8 string-dim columns, measure tables first) confirms **absence** for the honest not-found verdict — and
  **never abstains without that DB confirmation** (annotations only cover ≤30-card columns, so
  annotation-absence ≠ not-found → high precision, no false abstains).
- **Time grain** — `requested_time_grain(question)` vs `_available_grain(tables, measure_tables, req)`: a
  measure table with a finer time column → repair path; else the finest measure-table grain is the ceiling
  → answer-at-coarser caveat.
- Exposes `.feasibility` (`answerable` | `answerable_with_caveat` | `not_answerable`), `.caveat`,
  `.prompt_constraints` (the hard constraints handed to the generator).

**Wiring in `_stream_chat`** (`aughor/routers/investigations.py`, flag `ask.resolve_first`, default off,
byte-identical off): run `resolve()` once before the coder `.complete`; if `not_answerable` → **abstain
honestly** (emit headline+followups, save turn, return — NO empty query); else prepend `prompt_constraints`;
the single `caveat` leads the narrator too. **Phase 3 (first deletion):** when resolution ran, SKIP the
semantic `inspect` LLM call — its five checks ARE the verdict.

## Real-data bug caught by validation (the lesson)

The hermetic fixture was too simple. Run against the **actual** luxexperience connection, the first version
scanned entity + grain independently and bound Mytheresa to `brand_collaborations` (a decoy that also has
`platform=Mytheresa` + a `launch_date` DATE + `est_gmv_eur`), mistaking `launch_date` for a monthly-sales
path. **Fix = measure-first** (above). Re-validated on the real connection: binds
`financial_summary.platform='Mytheresa'`, available=yearly, feasible_via=None → honest "monthly unavailable,
annual only" caveat + correct constraints. The fixture now carries a `brand_collaborations` decoy so it
can't regress. **Always validate on the user's REAL schema (read-only, deterministic) — a toy fixture gives
false confidence.**

## Verification

- `tests/unit/test_answer_resolution.py` (9, incl. the decoy) — deterministic, no LLM.
- `tests/integration/test_resolve_first_runtime.py` (2) — abstain fires on the real `/chat` endpoint with the
  coder **never called**; flag-off reaches normal generation.
- Real-data verdict confirmed on the `workspace`/luxexperience connection (read-only).
- ruff + swallow/flag ratchets green; 217-test chat/investigation regression green (flag off = untouched).

## Pending (next session)

1. **Enable + test end-to-end with a responsive LLM.** The verdict logic is proven; the *found-entity* path
   still needs the coder to generate (flaky in the 2026-07-13 env). Enable `ask.resolve_first` (runtime
   toggle, no reload) and confirm on the real luxexperience canvas that the `fiscal_month` warning is gone,
   the headline is honest, and the caveat is grounded. The *abstain* path needs no LLM (already proven).
2. **Deletion roadmap** (the payoff — do AFTER the verdict is proven on real traffic, staged, each gated):
   the guards the verdict subsumes in `_stream_chat` — entity-column alignment (~1516), breakdown-grain
   (~1631), id-arithmetic guard+backstop (~1641/1769), ratio-of-sums (~1653), measure-grain caveat (~1756),
   scope guard (~1589); and collapsing the fan-out battery into "emit the fan-out-safe shape from the
   resolved join topology."
3. **Deep-path adoption** — thread the same verdict through `build_data_understanding`/`grounding_block()`
   so the ADA path inherits it (it already has intake validators; this unifies them).
4. **Entity resolution breadth** — high-card entities (customer names) need the DB probe path exercised;
   multi-entity questions; disambiguation when a value appears in >1 measure table.

## How to resume

`git checkout ground-first-resolution`; read this doc + `aughor/semantic/answer_resolution.py`; run
`pytest tests/unit/test_answer_resolution.py tests/integration/test_resolve_first_runtime.py`. To re-validate
on real data, `resolve(...)` against `open_connection_for("workspace")` (read-only). Plan file:
`~/.claude/plans/agile-leaping-cosmos.md`.

## Related session work (also unpushed)

Branch `2026-07-13-task-history` (8 commits, off `main`, NOT pushed): Rec 4 `task_history`
(`obs.task_table`), Rec 5 grounding-context receipt (`ask.context_receipt`, backend+UI+convergence), the
grain-feasibility disconnect fix (`grain.feasibility` — a **post-hoc** version now superseded by this
ground-first approach), and the time-series `computeSummary` fix. See `docs/PLATFORM_STUDIES_COMBINED_2026-07-11.md`.
