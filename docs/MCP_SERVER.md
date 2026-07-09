# MCP Server — Aughor's governed intelligence as MCP tools (R5)

> Status: **shipped** (branch `2026-06-21-agentic-fleet-metering`). The fleet's external-reach
> surface, from the MotherDuck synthesis ([`MOTHERDUCK_LEARNINGS.md`](MOTHERDUCK_LEARNINGS.md) R5,
> [`AGENTIC_ARCHITECTURE.md`](AGENTIC_ARCHITECTURE.md) §7).

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes Aughor's
**governed intelligence** as tools any MCP client (Claude Desktop, Claude Code, Cursor) can
call — so an external agent can ask Aughor a question and get a **verified answer with a Trust
Receipt**, not raw SQL.

## Why governed tools, not a raw `query` tool

A generic text-to-SQL MCP hands the model a SQL runner and hopes it writes a correct,
fan-out-safe, metric-consistent query. Aughor instead exposes `ask` / `deep_analysis` /
`get_metric` / `get_briefing` — tools that run Aughor's **full governed path**: write the SQL →
ground every number in real rows → enforce registered metric definitions → attach the guards
that fired. The answer is verified, not plausible.

> MotherDuck makes the *client* smart; Aughor makes the *tool* smart. (MotherDuck's own DABstep
> evidence: a governed semantic layer is what takes NL2SQL from "plausible" to correct.)

## The tools

| Tool | What it does | Governed because… |
|------|--------------|-------------------|
| `list_connections` | List the warehouses Aughor can analyze (call first). | — |
| `ask` | NL question → answer + **Trust Receipt** (SQL, rows sample, trusted metrics). | grounded in real rows; enforces governed metrics; receipt shows the guards. |
| `deep_analysis` | Run the autonomous Deep Analysis agent (ADA) for "why / driver" questions → report + receipt. | multi-step, fan-out- & grain-safe; hypotheses verified against data. |
| `get_investigation` | Fetch a Deep Analysis report by id (poll a long run, or re-read). | reads the journaled report. |
| `get_metric` | The governed value & definition of a registered metric. | runs the registered formula **with its declared filters** (e.g. revenue net-of-cancelled). |
| `list_findings` | The insights Aughor's background explorer already discovered. | each a verified finding with confidence + the SQL behind it ($0 read). |
| `get_briefing` | The executive Briefing — impact-ranked verdict, signals, citations. | built from governed metrics + verified findings; re-validated on refresh. |
| `explore` | Kick off autonomous background exploration of a connection. | subject to agent governance (a paused Scout won't auto-run). |
| `list_jobs` / `get_job` / `cancel_job` | The agent fleet — running/finished work, each with agent + real cost. | the legible view over the kernel's metered jobs. |

There is deliberately **no raw `query` tool**.

## Architecture

A standalone MCP server that is a thin **client over the running Aughor REST API** — not an
in-process import of the app:

```
 Claude Desktop / Code / Cursor
        │  (stdio or streamable-HTTP, MCP protocol)
        ▼
 aughor.mcp.server  (FastMCP — 11 governed tools, rich docstrings)
        │  aughor.mcp.client.AughorClient  (httpx; SSE-folds /chat + /investigate)
        ▼  HTTP  (AUGHOR_API_URL, X-Api-Key)
 Aughor REST API  ──►  the real governed path
        (metering · agent budgets · capability gating · Trust Receipts — in the API process)
```

Keeping it a client means every tool runs the **exact** governed path the web app runs (cost
metering, agent governance/budgets, capability gating, receipts all execute once, in the API
process), with no second `JobKernel` and no FastAPI-lifespan entanglement. The server stays
stateless and light (httpx only), so it starts fast under a stdio launcher.

## Running it

1. **Start the Aughor API** (the MCP server talks to it):
   ```bash
   uv run uvicorn aughor.api:app --port 8000
   ```
2. **Run the MCP server** (usually your MCP client launches this for you — see below):
   ```bash
   python -m aughor.mcp           # stdio  (Claude Desktop/Code/Cursor)
   python -m aughor.mcp --http    # streamable-HTTP on 127.0.0.1:8765
   ```

## Connecting a client

**Claude Desktop** — `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "aughor": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/aughor", "run", "python", "-m", "aughor.mcp"],
      "env": { "AUGHOR_API_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

**Claude Code**:
```bash
claude mcp add aughor --env AUGHOR_API_URL=http://127.0.0.1:8000 \
  -- uv --directory /absolute/path/to/aughor run python -m aughor.mcp
```

**Cursor** — `.cursor/mcp.json` (same shape as Claude Desktop's `mcpServers` entry).

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `AUGHOR_API_URL` | `http://127.0.0.1:8000` | The running Aughor API. |
| `AUGHOR_API_KEY` | _(unset)_ | Sent as `X-Api-Key` when the API enforces one (`AUGHOR_API_KEY` on the server). |
| `AUGHOR_MCP_TIMEOUT` | `60` | Timeout (s) for plain calls. |
| `AUGHOR_MCP_DEEP_TIMEOUT` | `300` | Timeout (s) for the streaming `ask` / `deep_analysis` tools. A `deep_analysis` that exceeds it returns an `investigation_id` to poll with `get_investigation`. |

## Verification (2026-06-21, live on `workspace`/missimi)

- **Real stdio MCP protocol** round-trip: `initialize` → 11 tools advertised → `call_tool`
  (the way Claude Desktop launches it).
- **`ask`** ("What is the total revenue?") → governed answer bound to the registered revenue
  definition (`… WHERE status <> 'cancelled'`), a grain trust-caveat, and a Trust Receipt
  (`artifact · lineage · job · cost`, real metering: 12,773 tokens / 1 query).
- **`get_metric`** assembled the governed query with its declared filter; **`get_briefing`**
  returned the live € narrative; **`list_findings`** the 4 real missimi findings; **`list_jobs`**
  real fleet cost metering.
- 19 unit tests (SSE folding, read tools, error surfacing, registry) + in-process real-path
  tests against the live FastAPI app; 1,286 unit tests green; zero net ratchet debt.

## Backlog

- **Auth depth** — today the optional `X-Api-Key` mirrors the API; richer per-client scoping
  rides on the planned platform auth (#12).
- **Streaming progress** — `deep_analysis` is blocking-with-timeout + poll; MCP progress
  notifications could stream phase updates.
- **Resources/prompts** — expose briefings/findings as MCP *resources* and common asks as MCP
  *prompts*, not only tools.
