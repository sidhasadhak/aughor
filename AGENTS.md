# Working on Aughor

Conventions an agent needs before changing this repo. Short on purpose — the long-form
reasoning lives in the wave arc docs under `docs/`.

## Ground rules that have been paid for

- **Measure the premise before building on it.** Wave G's program prose was wrong or stale
  on four of seven items, each found by reading the code first. A pre-check that takes ten
  minutes has repeatedly changed or cancelled a day of work.
- **Grep the data, not just the source.** Wave G3 concluded a dimension was empty by
  grepping for `role=` and finding twelve empty literals; the live data was 100% populated,
  because the value is resolved at runtime. Both mistakes are cheap to avoid and expensive
  to ship.
- **Green tests are not proof.** Run the thing and show the output. Wave G5's clearance
  trim passed twenty tests while silently never firing on a real graph, because every
  fixture happened to make two different names equal.
- **Fix a ratchet at the cause, never by raising its baseline.** If a check fires, the
  answer is usually to promote a name, register a constant, or wire a guard — not to move
  the number.

## Invariants

- **Provenance is required.** No store accepts a fact without a source, and no model
  authors one. There is deliberately no `llm_inferred` provenance.
- **Flags are off by default and byte-identical when off**, with a test asserting it. A
  flag graduates on a receipted `GraduationDecision`, never on green tests.
- **One store per concept.** This repo has three times found the same bug: five
  mutually-unaware eval surfaces, thirteen spellings of "out of date", five audit sinks.
  Before adding a store, search for the four that already do most of what you want.
- **Withheld is said, never implied.** A trimmed answer, a blocked action, an unpriced
  model and an unchecked table each say so. An empty result that means "you may not see
  this" teaches the reader the data does not exist.
- **Supersede, do not delete.** Findings, ontology overrides and artifacts are superseded
  with history intact. The exceptions are deliberate and documented where they occur.

## Practicalities

- **Lint:** `uvx ruff@0.15.20 check .` (not `uv run ruff`).
- **Tests:** run targeted — `pytest -k "ratchet or contract or <your area>"`. A full local
  run has twice destroyed `data/`; each store honours an `AUGHOR_*_DB` override registered
  in `tests/conftest.py`, and a new store must be added there.
- **`data/` is partly TRACKED on purpose** — `data/context_graph/`, `data/ontology_overrides/`
  and `data/vocabulary/` are governed artifacts a reviewer should see in a diff. Snapshot
  before any migration and verify with `git ls-files data/` after.
- **Frontend has four gates**, and `tsc --noEmit` is silently useless while the dev server
  runs (a generated `.next/dev/types` file carries a parse error and tsc aborts). Delete it
  first. Adding a route means regenerating the typed client: `cd web && npm run gen:api`.
- **Never `git stash` while the web dev server is watching.**

## Where to start reading

`ROADMAP.md` §0 for status, `docs/PLATFORM_PROGRAM_2026-07-26.md` for the forward plan, and
the wave arc doc for whatever you are touching — each one opens with the survey that set
its scope, which is usually the fastest way to learn why the code looks like it does.
