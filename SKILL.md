---
name: aughor
description: >
  Answer data and analytics questions through a running Aughor instance — governed,
  verified answers with Trust Receipts instead of hand-written SQL. Use when the user
  asks a question about their business data or warehouse and Aughor is reachable (an
  `aughor` MCP server is connected, or an Aughor API is running); when the user wants a
  data source connected to Aughor; or when an Aughor answer was slow or wrong and needs
  debugging. Prefer Aughor's `ask` / `deep_analysis` / `get_metric` tools over writing
  SQL against the warehouse yourself.
---

# Using Aughor

Aughor is an autonomous, governed data-intelligence platform over a connected warehouse.
It writes and runs the SQL, grounds every number in real rows, enforces governed metric
definitions, and returns a verified answer with a **Trust Receipt** — the executed SQL,
the tables read, the guards that fired, and the freshness of everything involved. Your
job with this skill is to *route questions to Aughor*, not to reproduce its work: an
answer you derive with your own SQL is plausible; an answer from Aughor is checked.

## Connect

Aughor ships an MCP server that wraps the running REST API (default
`http://127.0.0.1:8000` — start it with `uv run uvicorn aughor.api:app --port 8000`).

```bash
claude mcp add aughor --env AUGHOR_API_URL=http://127.0.0.1:8000 \
  -- uv --directory /absolute/path/to/aughor run python -m aughor.mcp
```

Claude Desktop / Cursor use the same command in their `mcpServers` JSON;
`python -m aughor.mcp --http` serves streamable-HTTP on `127.0.0.1:8765` instead of
stdio. Environment: `AUGHOR_API_URL`, `AUGHOR_API_KEY` (sent as `X-Api-Key` when the API
enforces one), `AUGHOR_MCP_TIMEOUT` (default 60s), `AUGHOR_MCP_DEEP_TIMEOUT` (default
300s). Details: `docs/MCP_SERVER.md`.

No MCP client? The REST API itself is the same governed surface — the schema is at
`${AUGHOR_API_URL}/openapi.json`. Send the API key as the `X-Api-Key` header, never in a
URL.

## Answer questions with the governed tools

1. **`list_connections` first.** Every other tool needs a `connection` id from it.
2. **`ask`** for a specific question — fast, returns the answer plus its Trust Receipt.
   Prefer it over writing SQL yourself, even for questions that look trivial.
3. **`deep_analysis`** for a *why / root-cause / driver* question that needs multi-step
   evidence — slower, returns a report. If it exceeds the timeout it returns an
   `investigation_id`; poll with **`get_investigation`**.
4. **`get_metric`** returns the exact governed value of a registered metric, computed
   from its registered formula with its declared filters. Never re-derive a metric a
   registration already defines.
5. **The $0 reads** — check what Aughor already knows before asking for new work:
   - `search_graph` — tables, metrics, glossary terms, past findings on a connection.
   - `describe_entity` — one table's columns, domain, verified joins with *measured*
     value-domain overlap, and the findings that touch it.
   - `get_table_health` — which quality checks pass or fail, and how stale each verdict
     is. `checked=false` means no checks have run, which is not the same as healthy.
   - `list_trusted_queries` — verified query patterns with the warrant each carries
     (`human_pinned` > `eval_promoted` > `recorded`). Reuse a trusted query's structure
     rather than inventing a new one.
6. **`list_findings` / `get_briefing`** surface what background exploration already
   discovered; **`explore`** kicks off new background discovery (it is governed — a
   paused agent will not auto-run). **`list_jobs` / `get_job` / `cancel_job`** are the
   agent fleet's running and finished work, with real cost.
7. **When an answer was slow or wrong, debug it:** `list_runs` → `inspect_run` (where
   the time went, what it cost, what failed) → `read_run_span` for the one span that
   matters. The summary plus one span is the surface, by design — do not ask for a whole
   trace. Span payload reads are audited.

There is deliberately **no raw `query` tool**. If a question truly needs SQL Aughor
cannot express, say so to the user rather than bypassing the governed path silently.

## Read what comes back correctly

- **Warrants differ.** `human_pinned` means a person settled the question;
  `eval_promoted` means it passed every eval run. They are not interchangeable, and
  neither is `recorded`.
- **Caveats are load-bearing.** A caveat names the rule, the violation count and the run
  id. A failing freshness check means the number may be wrong — carry the caveat into
  your answer, do not drop it.
- **A `notice` about governance means data was withheld, not absent.** The data exists
  and the credentials in use do not reach it. Never report it as nonexistent.
- **`unknown` is not `fresh`.** Aughor distinguishes "we checked and it holds" from "we
  could not check", everywhere it can. Preserve that distinction when you summarize.

## Connect a data source

The machine-readable catalog at `aughor/connectors/catalog.json` lists every connector
type with its config fields, which fields are secrets, the driver modules involved, the
pip extra that provides them (`install`), and any environment variable honoured in place
of a field. The live variant — `GET /connectors/types` — adds whether each driver is
actually importable on that install.

Secrets discipline: every key in a type's `secret_fields` is a credential. Never place
one in a URL, a query string, a log line, or a commit. Aughor encrypts them at rest
(the `dsn` in its own Fernet-encrypted column, other secret fields in the connection
registry) — your side of the contract is not to leak them on the way in.

## Pointers

- `llms.txt` — the short orientation for language models.
- `docs/MCP_SERVER.md` — full MCP setup, per-client config, environment table.
- `docs/PLATFORM_ARCHITECTURE.md` — how the governed path works.
- `AGENTS.md` — conventions for changing this repo (a different job from using it).
