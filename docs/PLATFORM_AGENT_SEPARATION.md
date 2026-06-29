# Platform ↔ Agent separation — decision record

> **Status:** implemented (2026-06-30, branch `2026-06-29-platform-agent-separation`).
> Records *why* and *how* the **Data Intelligence Platform** (the home) is separated
> from the **Aughor Agent** (the intelligence), and the invariant that keeps them so.

## Thesis

Aughor is two things in one codebase:

- **The Data Intelligence Platform (DIP)** — the *home*: tenancy (org/workspace),
  the catalog/metastore, connectors, storage, compute lanes, the security/audit gate,
  the job kernel + ledger + metering, LLM/inference vending, the HTTP/MCP surfaces,
  licensing, secrets. It has independent, plug-and-play mechanics.
- **The Aughor Agent** — the *intelligence* that runs **within** that home: the
  explorer, ADA/investigate, insight modes, the ontology + semantic compiler +
  metrics, knowledge & briefings, playbook, packs, profile, verify, evidence.

The separation is **logical-first** (one `aughor` package, an enforced boundary; a
physical two-package split is a later, now-mechanical move) and the boundary is built
for an **extensible** future (a *different* agent could plug into the same platform).

## The one rule (Invariant #8)

> **Platform ≠ Agent.** The **Agent may import the Platform** (that is the data plane
> calling the control plane — the allowed direction). The **Platform must never import
> the Agent.** Enforced by `tests/unit/test_platform_agent_boundary.py` — a stdlib
> `ast` ratchet with an **empty** allowlist: any new platform→agent import fails CI.

Membership: **Platform** = `db`, `kernel`, `connectors`, `metastore`, `org`,
`platform`, `security`, `llm`, `mcp`, `licensing`, `workspace`, `orgsettings`,
`volumes`, `canvas`, `export`, `savedquery`, `actions`, `secretvault`, `stats`,
`telemetry`, + the SQL inspectors. **Agent** = `agent`, `explorer`, `ontology`,
`semantic`, `knowledge`, `briefs`, `playbook`, `packs`, `profile`, `verify`,
`evidence`, `semops`, `monitors`, `memory`, `process`, `tools`, `rules`, `sql/writer`.
**Host/wiring seam** (may reference both): `routers/`, `api.py`, `cli.py`, `mcp/`.

## The contract — two halves

1. **Downward (what the platform offers the agent)** —
   `aughor/platform/contracts/host.py`: a `HostCapabilities` Protocol + `default_host()`
   naming the data plane, inference vending, the job/ledger substrate, the security
   gate, and the grant-scoped catalog view. The agent reaches these through their
   stable module functions today; the Protocol makes the surface explicit and
   substitutable. Plus `aughor/platform/contracts/execution.py` — the `QueryResult`
   execution-result contract every connector returns.

2. **Upward (what the agent plugs into the platform)** — the registries under
   `aughor/kernel/registries/`, populated by `aughor/agent/bootstrap.py`
   `register_agent_plugins()` (called at the api lifespan, the cli, and the test
   conftest). With nothing registered the platform runs **raw** — proven by
   `tests/unit/test_plug_and_play.py`. The live contributions are introspectable via
   `aughor.kernel.registries.manifest()`.

| Registry | Seam it inverts | Agent contribution |
|---|---|---|
| `purge_hooks` | `db/purge.py` delete cascade | per-store `purge(conn_id/schema/inv_ids)` |
| `ingestion` | connector→indexer, history→RAG, registry→cache | `ingest(kind, **payload)` sinks |
| `schema_annotators` | `db/connection` `get_schema`/`build_intelligence` | `enrichment` · `intelligence` · `exploration` |
| `execution_hooks` | `db/connection` `ai_sql` reach-ins | post-execute receipt · on-connect UDFs |

## What inverted (the four patterns)

- **A. Contract types** — `QueryResult`/`StatResult` moved to the platform contract;
  `agent/state.py` re-exports for back-compat.
- **B. Schema enrichment (the "god file")** — `db/connection.py` rendered the raw
  schema *and* baked in glossary/ontology/exploration. Now the platform renders raw
  (`db/schema_render.render_raw_schema`) and runs registered annotators. The three
  divergent per-connection recipes (DuckDB/Postgres/SQLite) were **unified** into one
  pipeline; the DuckDB hot path is byte-identical (modulo pre-existing value-order
  non-determinism). `ai_sql` provenance/UDFs moved to `execution_hooks`.
- **C. Teardown cascade** — `db/purge.py` imported ~10 agent stores; now it runs
  platform steps inline and calls registered purge hooks (count-parity preserved).
- **D. Ingestion/events** — knowledge connectors, investigation-RAG indexing, and
  profile-cache eviction emit via `ingest(...)`; the agent registers the sinks.

## Next (deferred, now cheap)

- Physical two-package split (`dip/` + `aughor_agent/`) — a mechanical move once the
  boundary test is green, which it is.
- Route the agent's platform access through `HostCapabilities` at call sites (currently
  direct module functions — already the allowed direction).
- `connectors/file/sqlite.py` and Postgres now share the unified enrichment; revisit if
  a connector needs a lighter recipe.
