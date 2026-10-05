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
| `search_graph` / `describe_entity` / `get_table_health` / `list_trusted_queries` | What Aughor already knows: the knowledge graph, one object type, a table's quality verdicts, the trusted query patterns. | $0 reads, through the API (DE-2c) under the caller's organisation and clearances. |
| `list_runs` / `inspect_run` / `read_run_span` | Debug an answer: which runs, one run's shape, one span's payload. | the summary plus one span, never a whole trace. |
| `read_contract` / `read_claims` / `read_restatements` / `post_claim` | The ledger API (the 2027 study's phase 7): read the agent contract, read claims as recorded on a date, read what was restated since a cursor, and post a claim **with its warrant** as yourself. | the ledger's laws at the door (no fact without a warrant, no model-authored fact above `said`, no stated confidence); the author is the principal, scored by what becomes of its entries. |

There is deliberately **no raw `query` tool**. The ledger API behind the last row is also served over
REST under `/ledger/v1` (`docs/AGENT_CONTRACT.md` is the published contract), where an outside vendor's
agent presents a **service principal** (`X-Aughor-Service`, `X-Aughor-Service-Key`, minted by a person
at `POST /ledger/v1/principals/service`) and is held to the same agent policy as this server.

### What each tool needs — and the organisation's agent policy (DE-2b)

Every tool is one of three things, and says so in its MCP hints: a **read** (`readOnlyHint`)
looks things up; a **run** starts explorations and analyses, which spend model calls; an
**act** (`destructiveHint`) changes something — `cancel_job`, an exposed automation, Spotlight's
staged acts. Which of the three an outside agent may do is the organisation's **agent policy**:

| | |
|---|---|
| Where it lives | `GET /org-settings/agent-policy` — the saved policy, the environment's narrowing and the effective result. Kept with the organisation's other per-org setting (the LLM binding's store), not a new store. |
| Default | `run`, set by nobody: today's exposure made explicit. `act` is given only by a person. |
| Who sets it | `PUT /org-settings/agent-policy` `{"level": "read"\|"run"\|"act", "connections": [...]?, "tools": [...]?}` — a person with `ADMIN_MANAGE_ORG`. An agent that tries is refused with `AGENT_POLICY_NOT_SELF_SET`. `DELETE` returns to the default. |
| Allowlists | `connections` (connection ids) and `tools` (tool names); `null` means all. |
| Environment | `AUGHOR_AGENT_POLICY_LEVEL`, `AUGHOR_AGENT_POLICY_CONNECTIONS`, `AUGHOR_AGENT_POLICY_TOOLS` (server side) can only **narrow** what is saved, never widen it. |
| Enforcement | Every call this client makes carries `X-Aughor-Agent: mcp` and `X-Aughor-Tool: <tool>`; the API checks the policy on those calls and refuses with a 403 whose `detail.code` is one of `AGENT_LEVEL_DENIED`, `AGENT_TOOL_DENIED`, `AGENT_CONNECTION_DENIED`, `AGENT_POLICY_NOT_SELF_SET`. The server also hides a disallowed tool from `tools/list` and refuses one called by name with the same code. |
| Audit | Every agent call, allowed or refused, is a `mcp.tool_call` event in the Ledger with its principal, tool, route, verdict and bounded arguments — listed on the governance feed under *data access*. |

## Architecture

A standalone MCP server that is a thin **client over the running Aughor REST API** — not an
in-process import of the app:

```
 Claude Desktop / Code / Cursor
        │  (stdio or streamable-HTTP, MCP protocol)
        ▼
 aughor.mcp.server  (FastMCP — eighteen governed tools plus the opted-in automations and
        │           the Spotlight roster; lists what the organisation's agent policy allows)
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
   AUGHOR_MCP_TOKEN=… python -m aughor.mcp --http                  # streamable-HTTP on 127.0.0.1:8765
   AUGHOR_MCP_TOKEN=… python -m aughor.mcp --http --host 0.0.0.0   # …served to other machines
   ```
   `--http` needs `AUGHOR_MCP_TOKEN` and refuses to start without it (DE-2a, ROADMAP §3.51): every HTTP
   client presents it as `Authorization: Bearer <token>`, because the tools behind it call the API with this
   process's own key and principal. Make one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   The transport security is built for the host actually served — before DE-2a a loopback-only allowlist was
   fixed at import, and `--host 0.0.0.0` answered every remote client `421 Invalid Host header`.

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
| `AUGHOR_MCP_ORG` | _(unset)_ | The principal this server acts as when the API requires identity (`AUGHOR_REQUIRE_IDENTITY=1`) and no OIDC issuer is configured: sent as `X-Aughor-Org`, with `AUGHOR_MCP_USER` (default `mcp`) as `X-Aughor-User`. Unset, every MCP call is refused with a 401 in identity mode (DE-2a). |
| `AUGHOR_MCP_USER` | `mcp` | The user the server acts as, beside `AUGHOR_MCP_ORG`. |
| `AUGHOR_MCP_BEARER` | _(unset)_ | An OIDC token for an API with an issuer configured, sent as `Authorization: Bearer …`. |
| `AUGHOR_MCP_TOKEN` | _(unset)_ | **Server side, `--http` only.** The bearer every HTTP MCP client must present; `--http` refuses to start without it. |
| `AUGHOR_AGENT_POLICY_LEVEL` | _(unset)_ | **API side (DE-2b).** Caps every organisation's agent policy at `read`, `run` or `act`; it can only narrow what an organisation saved. |
| `AUGHOR_AGENT_POLICY_CONNECTIONS` / `AUGHOR_AGENT_POLICY_TOOLS` | _(unset)_ | **API side.** Comma-separated allowlists intersected with the organisation's own. |

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
