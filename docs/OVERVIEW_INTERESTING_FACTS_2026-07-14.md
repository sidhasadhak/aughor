# Overview mode — "Show me interesting facts about this schema" (2026-07-14)

*Status: backend BUILT + live-verified on the real airline schema (branch `overview-mode` off
`agentic-platform`). The methodology answer to the user's question: how to configure Aughor to answer
the widest-possible question well, as a great new-user starting point — the way Databricks Genie
offers it by default in every space, but grounded and inspectable.*

## The problem (observed)

Asked "Show me interesting facts about this schema" on a 17-table airline dataset, Aughor routed to
the **Deep Analysis cross-sectional scanner** — a machine built to answer *"where is a metric
weakest?"*. Its intake defaulted to **one** metric (`SUM(tickets.fare_chf)`) and ranked it
"weakest first" across ~5 dimensions. It never touched the other 15 tables (bookings, 26.8K loyalty
members + 148K transactions, 261K baggage rows, refunds, upgrades, delays…) or any other measure.
An *investigation* answering an *exploration* question — one metric, weakness-framed, 15/17 tables
unseen.

## The reframe

"Interesting facts" is **schema profiling ranked by notability and capped for diversity**, not an
investigation. Genie's trick is that it *reads a profile of the data* — it doesn't launch an
analysis. That's why it's instant and broad. Aughor answers the same way, but every fact is
execution-grounded with its SQL and the notability ranking is deterministic, not a black box.

## The seven lenses

Each is a cheap grounded probe; most read one `SUMMARIZE` per table (no extra SQL, no LLM):

| Lens | What it surfaces | Airline example (live) |
|---|---|---|
| **scale** | rows, tables, time span, single-period | 273.9K tickets across 17 tables |
| **concentration** | HHI / top-1 share per dimension | 95.3% of fare from `flown` segment_status |
| **outlier** | a group's per-record value far from peer median | `hon_circle` fares 29% above typical |
| **distribution** | skew (mean/median), span (min→max) | refund_chf right-skewed: median 90, mean 344 |
| **composition** | the mix split of a categorical | segment_status: flown 95%, cancelled 3%, no-show 2% |
| **coverage** | single-value columns, high nulls, untouched big tables | baggage + boarding_passes untouched; "every row is EUR" |
| **relationship** | a measure that scales structurally across a small dimension | fare scales **51×** first-vs-economy per ticket |

## The pipeline

`profile (SUMMARIZE) → probe 7 lenses → score by notability → select diverse top-N → tour`

- **Notability** (`aughor/overview/metrics.py`, all new — no HHI/skew helper existed): HHI, Gini,
  skew ratio, spread ratio, median-relative deviation, each mapped onto a comparable `[0,1]`
  interestingness via saturating normalizers, so a 0.7 concentration and a 0.7 outlier feel equally
  notable.
- **Diversity selection** (`build.py::_select`): pass 1 takes the single most-notable fact of each
  lens (guarantees breadth of *types*); pass 2 fills by score under caps — ≤2 per lens, ≤2 per
  (table, dimension) cut — so the tour spans the schema instead of ranking one measure N ways.
- **Determinism + bounds**: no LLM, ≤14 tables scanned, ≤26 group probes, ~0.5s. Templated
  (not LLM-authored) headlines. This is what makes it graduation-eligible as a default.

## Guards learned from live validation

Real data on two schemas (airline + luxexperience) surfaced these, each now a guard with a test:
skip boolean flags (no "concentrates in True"); require **non-negative** measures (a signed
`award_miles` net makes concentration meaningless); collapse untouched-table facts into one; outlier
XOR relationship per cut (no double-count of the same insight); fraction-correct percentages
(`0.953` → "95.3%", not "0.95%").

## Wiring (how it's configured in Aughor)

1. **Routing** — a deterministic short-circuit in `_stream_ask` (mirrors the federation/program
   pattern), *before* the clarify gate: an under-specified "tell me about this data" IS answered by
   an overview, not a clarifying question. Detection = overview phrasing (`_OVERVIEW_RE`) **and**
   the absence of a named metric/entity/time window (a signal-absence guard strips the phrasing +
   generic dataset nouns first, so "tell me about revenue" still routes normally).
2. **Scope** — resolves the same `ExecutionScope` the chat path uses, so a canvas bound to a schema
   (a Genie-style "space") profiles exactly that schema; a bare connection profiles the lot.
3. **Emission** — `route{depth:"overview"}` → `overview_report{facts}` → `headline` → `done`.
   Reuses the profiler's read-only `__overview__`-labelled probes (audit/PII-exempt internal).
4. **Flag** — `ask.overview`, **graduated to `AUTO_ELIGIBLE`** (on by default via
   `capabilities.auto`) because it is bounded and deterministic and fires only on its trigger — the
   intended default first-look. An explicit env `=0` disables it.
5. **Reuse note** — the shared column profiler assumes bare table names resolve via `search_path`;
   on the multi-schema workspace DuckDB only schema-qualified names work, so the overview profiles
   itself (one `SUMMARIZE` per qualified table). Robust across connection types; no profiler change.

## Where it becomes the default new-user experience

Because it's cheap, broad, and grounded, "Show me interesting facts about this data" is the ideal
first chip on any new connection's empty state — Aughor offering it by default, exactly like Genie,
but with a Trust-Receipt-grade SQL behind every fact.

## Next

Frontend fact-tour renderer (a diverse card grid, tiny per-fact charts, collapsible SQL); the empty-
state suggestion chip; then live UI verification. Possible follow-ons: a one-line frontier synthesis
over the selected facts (kept deterministic for v1); "explore this fact" drill from a card into a
normal investigation; per-connection notability tuning from which facts users actually click.
