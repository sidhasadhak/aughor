# Design — the demo pack: baking finished intelligence into a shippable artifact

**Status:** designed, not built. 2026-08-03.

## What it has to do

Ship a connection's **finished intelligence** — explore, briefing, ontology, quick asks,
deep analyses — so a visitor lands on a hosted UI and sees real work immediately, with **no
model calls, no API key, and no spend**. Asking a *new* question requires the visitor to
bring their own backend (already shipped: Settings → System → Backend, #251).

The demo is a showroom of completed reasoning, not a live agent.

## What already exists (measured)

| Mechanism | Covers | Verdict |
|---|---|---|
| `ontology/interchange.py` (Wave O7) | curation only — synonyms, formats, value dictionaries, exclusions | **reuse as-is** |
| `ontology/context_graph_export.py` (Wave C6) | the context graph as a self-contained offline pack | **reuse as-is** |
| `data/context_graph/**` | already **git-tracked** (packs exist for aughor_ops, samples, workspace) | precedent for shipping artifacts in-repo |
| `data/history.db` → `investigations` | investigations, `report_json` **already a JSON column** | **gap — needs the new piece** |
| briefing | rendered from a `conn:schema` cache entry | **gap** |

Two of four layers already have export machinery, and one of them (`context_graph_export`)
was written for exactly this consumer: *"a teammate consumes it with no LLM, no API key, and
no Aughor running. Generation is paid once; consumption is free."* That is the demo's thesis,
already stated in the codebase.

The gap is investigations + briefing. Everything else is assembly.

## The design

### A pack is a directory of JSON, tracked in git

```
data/demo_packs/superstore/
  pack.json          # envelope: version, connection meta, provenance, generated_at, model
  investigations/    # one file per frozen run (explore · briefing · quick × 5 · deep)
  curation.json      # ontology/interchange.py export_bundle()
  graph/             # ontology/context_graph_export.py pack (graph.json + skills/)
```

Tracked, not gitignored — following `data/context_graph/`, which is deliberately tracked
for the same reason. At Superstore's scale this is small: the DB is 1.5 MB and a 37 KB
report is the large end, so a full pack lands in the low single-digit MB. It ships **inside
the container image**, no volume.

### Why JSON files and not a seeded SQLite

`interchange.py` states the rule this has to respect: *"The bundle is a VIEW over the stores
that already exist … never a parallel format with its own copy of the truth."*

For curation that means read the stores. For **investigations it is inverted**: the report
*is* JSON already (`investigations.report_json` parses to `{headline, sql, columns, rows,
chart_type, tables_used, intent, approach, insight}`), so a JSON file is not a second
representation — it is the same representation, moved. There is no drift risk because
nothing else derives it.

Committing `history.db` instead would be wrong on three counts: it is a **live store the
suite mutates** (the `registry-not-test-isolated` class of bug that once emptied the live
registry), it is an opaque binary in review, and it carries **670 workspace investigations
containing real business data** that must never ship.

### The export must be filtered, and that filter is a safety gate

`data/history.db` holds 724 investigations: **670 on `workspace`** — real `amazon` /
`luxexperience` / `main` data — and only 39 on `fixture`. Exporting by connection id is not
a convenience, it is the control that stops private data reaching a public demo.

The exporter therefore takes an explicit connection id and an explicit allowlist of
investigation ids, and **refuses** a pack whose rows do not all belong to that connection.
Default-deny, not filter-after-the-fact.

### Round-trip is the gate

`interchange.py` sets the bar: *"Export → import → export must produce the identical bundle.
Anything less means one of the two directions is lossy, and a lossy round-trip is worse than
no interchange at all: it looks like a backup."* It ships `round_trips(connection_id)` as an
executable check.

The demo pack gets the same gate: `pack_round_trips(pack_dir)` — export → import into a
throwaway store → re-export → byte-compare. This is the test that makes a re-bake safe, and
without it a regenerated pack could silently lose findings.

### Read-only at serve time

The demo container needs no import at all in the simplest form: a **read-only pack reader**
serves investigations straight from the files. That keeps the container stateless — a
restart cannot corrupt the demo, and there is no migration story.

Import into real stores stays available (same code path) for the case where someone wants
the demo as a *starting point* on their own machine, which is a genuinely different product
moment and should stay possible.

### Demo mode, and what it must say

A `demo` posture where:
- the pack's investigations are listed and openable
- **new** asks are refused with a specific, honest message pointing at Settings → System →
  Backend — not a generic error, and not a silent failure
- no LLM binding is required for the container to boot

The refusal is the product surface here, so it deserves real copy: *"This demo shows
completed analyses. To ask new questions, connect your own backend."*

## Risks, ordered by how badly they bite

1. **Leaking workspace data into a public pack.** 670 of 724 investigations are real business
   data. Mitigation: default-deny export, explicit connection id, and a test asserting a pack
   contains no row from another connection. **This is the one that must not be got wrong.**
2. **A lossy re-bake.** Regenerating a pack after a schema change silently drops findings.
   Mitigation: the round-trip gate, run in CI over the shipped pack.
3. **Stale pack vs moved code.** A pack generated today, rendered by a UI six months on. The
   envelope carries a version; the reader refuses a future one rather than mis-reading it —
   the rule `interchange.py` already applies with `BUNDLE_VERSION`.
4. **Demo mode leaking into normal use.** A flag-shaped posture that accidentally refuses
   real asks. Given the flag endgame is deleting flags, this should be an explicit
   deployment env var, not a new registry flag.

## Build order

1. `aughor/demo/pack.py` — `export_pack(connection_id, investigation_ids, out_dir)` with the
   default-deny filter; `read_pack(dir)`; `pack_round_trips(dir)`.
2. Tests: round-trip; **cross-connection refusal**; version refusal.
3. Wire curation + graph via the two existing exporters.
4. Read-only serve path + demo-mode refusal copy.
5. **Only then** spend on the runs, once into a pack that is known to round-trip.

Step 5 last is the point of doing this first: the expensive artifacts land in a container
that has already been proven to carry them losslessly.

## Open question for the run itself

Ontology → explore → briefing → analyses is the dependency order; each layer feeds the next.
Worth confirming before spending, because running out of order produces thinner artifacts and
the spend is not repeatable for free.
