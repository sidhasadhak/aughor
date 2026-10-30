<div align="center">
  <img src="web/public/aughor-logo.jpeg" width="110" alt="Aughor" />
  <h1>Aughor</h1>
  <p><strong>The agentic data intelligence platform.</strong></p>
  <p><em>Connect to your data. Let insights find you.</em></p>

  <p>
    <a href="https://github.com/sidhasadhak/aughor/actions/workflows/ci.yml"><img src="https://github.com/sidhasadhak/aughor/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-black" alt="License: Apache-2.0" /></a>
    <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: alpha" />
    <img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python 3.11+" />
  </p>

  <p>
    <a href="#quick-start"><strong>Quick start</strong></a> ·
    <a href="#pick-your-models"><strong>Models</strong></a> ·
    <a href="#whats-inside"><strong>What's inside</strong></a> ·
    <a href="ROADMAP.md"><strong>Roadmap</strong></a> ·
    <a href="FEATURES.md"><strong>Features</strong></a>
  </p>

  <a href="#the-96-second-tour"><img src="docs/readme/hero.png" width="900" alt="Aughor — Connect to your data. Let insights find you. The Briefing, Agent Ops and the Semantic Layer on the Superstore sample data" /></a>
  <p><a href="#the-96-second-tour"><strong>▶ Watch the 96-second tour</strong></a> — filmed on the Superstore sample data, every screen live</p>
</div>

---

Aughor connects to your warehouse and **keeps learning from it**. It explores the data on its own, learns what the business is, writes the metrics into a governed semantic layer for you to review and approve, and briefs you with every number cited. When you do ask — in plain English, in the SQL editor or as an analyst agent you built — the answer comes with **evidence, guards and a receipt**.

> **The thesis:** most AI data tools are query wrappers — you ask, they translate. Aughor explores your data in the background, forms a business ontology, and is engineered so the numbers it reports are **trustworthy, not just plausible**: deterministic guards sit between the model and every figure you see.

- 🔭 **It explores on its own.** Connect a warehouse and it starts learning — no prompts — asking up to 300 questions of a dataset in a run, keeping a frontier of what it has already covered and re-exploring as schema and data move. An interrupted run says so and offers to continue.
- 🧠 **It learns the business, then writes the metrics.** A business profile inferred from the data proposes the metrics that matter, drawn from a map of about a hundred metric patterns so every area of the business is covered. You customise one into a draft, see the checks before you decide (what it changes, whether it runs, what it declares, what could be compared), and approve it — or a whole set of proposals — through an approval gate.
- 📰 **It briefs you, as the reader you are.** For each dataset the explorer drafts a guide — what counts as news, the fair comparisons, who reads it — and a person publishes it. Each edition is then written for one reader (Finance, Product, a team) by a model that first reads what the platform already knows: its deep analyses, findings and decisions, and what was said in Slack, email and documents. Every number cites its query, every block can be drilled, and code checks each one before it shows.
- 🤖 **Agentic, not agreeable.** Ask a hard question and it plans, runs the queries and tests your hunch before it agrees with it — a deep, multi-phase run you can steer, or a quick straight answer.
- 🛡 **It refuses to be confidently wrong.** Engine-driven trust guards (grain, fan-out, numeral grounding, premise validation, adversarial refutation) run on the answers; one row policy holds at every door; a statement that would change data is refused before it runs, and every query is on the record in Security & Audit.
- 📒 **It keeps a record, and closes the loop on decisions.** Inquiries, decisions, missions, claims and corrections. A decision can be taken from a dashboard, a Briefing figure, a Slack message, an email or a meeting's notes; it is reviewed on its date and scored against what would have happened anyway.
- 📊 **Spreadsheets and dashboards of your own.** Make a sheet from a file, a query's rows or nothing; edit it like a spreadsheet, chat with it, share it with the people you choose. Build dashboards over the ontology, with questions the agent answers on a rhythm.
- 🏭 **It adapts to your industry.** An airline gets load-factor and on-time performance; a retailer gets AOV and return rate — an industry pack guides, the data decides.
- 🔌 **It runs fully local.** Your warehouse, your models — nothing has to leave your machine. Its own state is backed up every hour something changes.

### The 96-second tour

https://github.com/user-attachments/assets/0f66b544-4d82-4059-9e08-2153fa4def5e

<sub>Filmed on the Superstore sample data, every screen live · <a href="docs/readme/aughor-launch.mp4?raw=true">full quality (19 MB)</a></sub>

<p align="center">
  <img src="docs/readme/briefing.png" width="900" alt="The Briefing on the Superstore sample data: Furniture Discounting Erodes Hidden Profit — the lead story with every figure cited, and the record in numbers" />
</p>

## Quick start

**macOS / Linux**

```bash
curl -LsSf https://raw.githubusercontent.com/sidhasadhak/aughor/main/install.sh | sh
```

**Windows**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/sidhasadhak/aughor/main/install.ps1 | iex"
```

The installer asks once which industries Aughor is for (airline, food delivery, logistics,
manufacturing, retail and e-commerce, SaaS). Press Enter to keep them all: each connection's industry
is then detected from its data. To answer without being asked, add `--industries retail,saas` (or
`all`, or `none`) — `curl … | sh -s -- --industries retail`, or set `AUGHOR_INDUSTRIES` — and change it
later in **Settings → Organization** or with `aughor industries`.

Next time, run `aughor`.

### What it installs, and where

Nothing needs to be installed first — not even Git — and nothing asks for admin.

| | |
|---|---|
| **The checkout** | `~/aughor` (`AUGHOR_DIR` to change it). A `git clone` when this computer has a working Git, otherwise the same code as a downloaded snapshot. |
| **uv** | Only if missing, from `astral.sh`. |
| **Python 3.11** | Through `uv python install`, into uv's own store. |
| **Node.js** | This computer's, if it is 20.9 or newer. Otherwise a private Node 24 into `.aughor/node/`, verified against nodejs.org's published SHA-256 before anything is unpacked. |
| **The `aughor` command** | Into uv's command folder, which is already on `PATH`. No shell startup file is edited. |
| **Logs** | `.aughor/logs/` inside the checkout. A failed step prints the end of its log and what to do next. |

**Disk.** About 2 GB after a full install — measured on macOS: ~1 GB for the Python
environment and ~1 GB for the web app's packages, plus the checkout and a web build. Re-running
the installer only redoes what changed.

**Platforms.** macOS and Linux through `install.sh`; Windows through `install.ps1`, which also
runs from Command Prompt. CI performs a real install on all three whenever the installer or
what it installs changes. WSL2 is expected to behave as Linux does, but nobody has measured
it, so this page does not claim it.

### Running it again, updating, uninstalling

```bash
aughor doctor           # uv, Python, Node, both ports, the state dir, PATH, the model, the latest backup
aughor update           # fetch and fast-forward, then re-run the install steps
aughor backups          # the backups of this install's own state, newest first
aughor restore <name>   # put one back — refused while the API is serving
```

**Backups.** While the API runs it backs up its own state every hour that something changed —
each SQLite store through SQLite's backup API and checked, every other file copied as it is —
into `data/backups/`, and takes a checked, labelled copy before every migration; a copy that
fails holds the migration back. A restore lists every removal it would bring back and asks
first, keeps a backup of the present, and never writes over the SQL audit log or the
model-call log.

`aughor update` refuses rather than guesses: a checkout with local commits the remote does not
have is **never** rewound, and local edits outside `data/` stop it with the files named.
Changes inside `data/` never block it — that is state the app writes. A snapshot install has
no remote to update from, so it tells you to re-run the installer, which leaves your data alone.

To **uninstall**, delete the checkout (`~/aughor`) and the `aughor` launcher in uv's command
folder — `aughor doctor` prints its path. Your connections, history, receipts, sheets and
their backups live under `data/` inside the checkout, so copy that out first if you want to
keep them.

### Installing without being asked anything

```bash
curl -LsSf …/install.sh | sh -s -- --industries all --no-start
```

| | |
|---|---|
| `--industries retail,saas` \| `all` \| `none` | Answer the one question up front (or set `AUGHOR_INDUSTRIES`). |
| `--no-start` | Install only; do not start or open a browser. |
| `AUGHOR_DIR=/some/folder` | Install somewhere other than `~/aughor`. |

### When it will not install

**Windows Defender flags `uv.exe`.** A known false positive. Exclude uv's folder, or install uv
yourself first from `astral.sh`, then run the installer again.

**A corporate proxy.** If a download fails with a certificate error, the installer now says so
and prints the three variables to set. TLS-inspecting proxies re-sign connections, and Python,
Node and curl each need their own pointer at your organisation's CA bundle:

```bash
export CURL_CA_BUNDLE=/path/to/ca-bundle.pem
export SSL_CERT_FILE=/path/to/ca-bundle.pem
export NODE_EXTRA_CA_CERTS=/path/to/ca-bundle.pem
```

**A flaky network.** Downloads retry three times, and a throttled GitHub falls back to a
blobless clone and then to a snapshot. If it still fails, the log named in the error has the
underlying reason.

## Pick your models

Aughor **ships no default model** — nothing is assumed about another vendor's catalogue, so you name one before your first question. The one route to a model is **Settings → Models** in the web UI: pick a backend, and the picker lists what that backend actually serves (plus your custom entries). Backends: **Ollama · LM Studio · Groq · Together · Anthropic · Gemini · OpenRouter** (OpenRouter and Gemini both have free tiers).

- **Three roles, independently pluggable:** SQL generation (`coder`), report synthesis (`narrator`), and the fast interpret sub-tier (`fast`) each resolve on their own — run a fast structured model for SQL and a stronger one for prose.
- **A fallback you choose and watch:** pick a fallback backend/model in Settings; when the primary fails, the chain fails over — and since the run narrates its hops in the chat stream, a failing primary can't hide behind a healthy fallback. Pin the chain order with `AUGHOR_FALLBACK_BACKENDS` when you need to.
- **Env is the fallback layer**, not the primary config: `cp .env.example .env` and set `AUGHOR_BACKEND` + a key for headless/deployment setups; Settings wins when both exist.
- The `aughor up` boot summary shows whether a backend and model are configured (no network call — it can't tell you the backend is *reachable*). The API serves without an LLM; questions fail until one answers.

Minimal fully-local `.env`:

```env
AUGHOR_BACKEND=ollama
AUGHOR_CODER_MODEL=qwen2.5-coder:14b
AUGHOR_NARRATOR_MODEL=qwen2.5-coder:14b
OLLAMA_BASE_URL=http://localhost:11434/v1
AUGHOR_EMBED_MODEL=nomic-embed-text
```

## What's inside

One corpus of intelligence behind many surfaces — the depth, mechanisms, and trade-offs live in **[FEATURES.md](FEATURES.md)**.

**Intelligence**
- **Briefing** — written per dataset from a **guide** the explorer drafts at the end of an exploration and a person publishes: the business, what each range is for, what counts as news, the fair comparisons and the **readers** — function groups such as Finance or Product, or the whole organisation. An **edition** is the Briefing for one range and one reader. The model first reads the range and what the platform already knows — its deep analyses, the explorer's findings, the decisions in force, and what was said in Slack, email and documents — then composes the edition from blocks (sentences, figures, bridges, tables, heat grids, a decision). Each block cites a governed source and can be drilled in place, and code checks every block before it shows. A figure outside its usual range is news; data that has ended is read as final to its last row; a comparison the data cannot support is withheld and says why; a sent edition is checked again against every source as it leaves.
- **Home, Inbox and Now** — Home prepares a desk from what is on record and takes a question; Inbox holds what deep analyses recommended and what became of each; Now is what needs you this week — sent, waiting, held, corrected.
- **Data Canvas** — **Agent mode is the default**: a deep, multi-phase run with a plan you can edit, streamed progress, and interrupt-anytime input; Quick mode for a straight answer. Runs are supervised jobs that survive a closed tab and reattach, every conversation restores from History, and you can answer as one of your own agents. A canvas has its own Briefing tab, and a question can carry a dashboard's ticked objects, or a whole set, as its subject.
- **Dashboards** — standing sets of cards a person keeps for one area, beside the Briefing: figures and charts, ontology-bound pieces (process boards, object tables, breakdowns that always add up to the whole, rows marked by a declared rule), and **questions** the agent answers on a rhythm the way the Data Canvas does. Start one from a pack's template or from a sheet; publish it to a group as a versioned App.
- **Deep analysis** — intake → baseline → decompose → dimensional → synthesize, with premise validation, period-over-period decomposition anchored to the data's real window, loss-intent and multi-lens scans, and a report that is honest by construction (one canonical grain, consistent units, charts that match their prose).
- **Autonomous exploration** — its passes named in every log for what they do (structure, questions, synthesis); up to 300 questions of a dataset in a run, shared across its domains; frontier-incremental and grounded in the actual schema by construction. Findings prove themselves with confirming queries and land in the Evidence Ledger.
- **Semantic layer & governed metrics** — metrics proposed from the business profile and a map of about a hundred metric patterns, so the proposals cover the business area by area; each proposal passes code gates before it is offered (a metric whose date cannot bound its rows is refused at approval). Customise one into a draft, review it against its checks and approve it through an approval gate — or adopt a set of proposals in one approval — each dated and marked measured. Money prints in the currency a person confirmed for its dataset. One precedence-ranked contract that chat, deep analysis and the explorer all read.
- **Ontology** — auto-built and human-editable with override-wins semantics: entities, relationships, lifecycles, and the processes and actions on them, versioned in releases and compiled into docs. Find any object by name from ⌘K, see what uses an entity, put an earlier version back or mark one retiring with its successor and a day; an automation can act on each object a segment newly admits; a pack's upgrade arrives as a diff of only what changed.
- **Record** — five ledgers (Inquiries, Decisions, Missions, Claims, Corrections), editable: add a hypothesis, mark a claim wrong, reopen a decision. A decision comes in from a dashboard question, a Briefing figure, `decide:` in Slack, its own email address, a Google file's comments, or a meeting's notes (the model proposes, a person confirms). It reads from where it arose to what was learned, is reviewed on its date, and is scored against what would have happened anyway.
- **Trust guards** — the layer that separates Aughor from a plausible demo: grain/fan-out/numeral/premise/refutation guards, one shared SQL-safety pipeline across every mode, earned-confidence computed (never asserted), snapshot-pinned receipts. One row policy holds at every door — a question's own SQL, the object door, MCP — and every object read says how complete it is; tables carry expectations (never empty, never repeated, fresh enough, not drifting), measured by an automation.
- **Adaptive temporal scope** — four tiers from activity-anchored recency to a cost governor for TB-scale warehouses.

**Data**
- **Connectors** — DuckDB · MotherDuck · PostgreSQL · **BigQuery** (run live in production against a real warehouse) · Snowflake · MySQL · SQLite · Exasol · Trino · local upload (CSV/Parquet/Excel) · S3 · Google Sheets · Stripe / HubSpot / Salesforce · Confluence / Notion, and federated queries across them. Credentials Fernet-encrypted at rest; a per-dialect capability contract keeps generated SQL runnable on each engine.
- **Spreadsheets** — sheets people make from a file, a query's rows or nothing, and edit as they would in a spreadsheet: keys, paste, undo, ranges, a menu and a sort on every header, pinned rows. Views of a sheet are boards, calendars and grouped totals with rules, and a column a model fills row by row is never counted in a figure. Combine sheets, chat with one (the answer says how many of what whole, and shows the rows on the grid), share it with chosen people and groups to read or edit, and make a dashboard from it. Every change is kept with who and when.
- **SQL Editor** — SQL or a visual composer; type `/ask` and a question and it writes the SQL; every statement is checked by the guards before it runs; results, charts, and open-in-editor from any answer.
- **Catalog & Documents** — browsable schema intelligence and glossary; a searchable corpus of the documents your agents read.

**Operations**
- **Agents & Agent Ops** — build your own analyst agents (instructions, a connection, the documents they read) and ask as them; each answer names the revision of the agent that gave it. Agent Ops holds the overview, the roster, what needs attention, automations, the hub map with each node's failure rate, and an action centre. Automations and monitors keep every definition as a version, a run names the one it ran under, a past run replays as a dry run, and a run's lines can be searched across the last thirty days. Approvals are risk-graded and audited.
- **Monitors, notifications & integrations** — findings become monitors; a monitor on a dated metric reads that metric's latest settled period, and an alert closes when its metric comes back within its limit. Alerts deliver to Slack, webhooks and Jira on guarded evaluations; Slack and Microsoft Teams bots, where "that's wrong" becomes a correction.
- **Spend** — usage and model cost by run, caps that stop a run and open a budget editor, and a governance feed that pages by date and exports.
- **Security & Audit** — every query checked and recorded, by person or agent: what was blocked, what was flagged, what was masked, and the gate map. An organisation can require a reason before anyone reads a run's details, recorded once.
- **Evals** — suites, runs and experiments in the app; golden-set, Spider 2 and ablation harnesses in `evals/`.
- **MCP server** — Aughor's governed answers as [MCP](https://modelcontextprotocol.io) tools (`python -m aughor.mcp`): Claude Desktop / Claude Code / Cursor get a verified answer with a Trust Receipt, not raw SQL. An administrator can also open doors through which outside agents read the ontology and propose its actions; every outside caller is someone — a service principal whose grant names the areas, entities, actions and connections it may use.
- **Agent skill & catalog** — [`SKILL.md`](SKILL.md) teaches a coding agent the governed workflow; [`llms.txt`](llms.txt) and a machine-readable connector catalog ([`aughor/connectors/catalog.json`](aughor/connectors/catalog.json), secrets flagged) make the platform legible to tools.
- **Security & RBAC** — fail-closed SQL safety gate, read-only Postgres, SSRF allowlist, prompt-injection fencing; org tenancy enforced on every read once `AUGHOR_REQUIRE_IDENTITY` is set, with a viewer ⊂ analyst ⊂ owner ladder, row-level policy compiled into every connector's WHERE, and row and property security on the ontology.
- **Backups** — the platform's own state backed up every hour something changed, a checked copy before every migration, and `aughor restore` to put one back ([above](#running-it-again-updating-uninstalling)).

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, LangGraph |
| Frontend | Next.js 16 (App Router, Turbopack), TypeScript, Tailwind, Radix Themes |
| Analytics | DuckDB, PostgreSQL, BigQuery |
| Charts | Vega-Lite — one grammar for screen and PDF/PPTX export |
| LLM runtime | Ollama · LM Studio · Groq · Together · Anthropic · Gemini · OpenRouter, per-role, with a chosen fallback chain |
| Statistics · SQL | scipy, numpy · SQLGlot |
| Observability | OpenTelemetry (GenAI semantic conventions) — point `AUGHOR_OTLP_ENDPOINT` at Jaeger/Tempo/Langfuse; unset = no export |
| State · Packaging | SQLite (history, registry, evidence, audit) · uv |

## Project structure

```
aughor/
├── aughor/
│   ├── agent/        # LangGraph investigative loop + phase prompts
│   ├── briefing/     # The Briefing — guides, readers, editions composed from blocks
│   ├── canvas/       # Data Canvas — scoped workspaces and their answers
│   ├── connectors/   # DuckDB, Postgres, BigQuery, Snowflake, Stripe, …
│   ├── dashboards/   # Dashboards — specs, pieces, questions, Apps
│   ├── db/           # State stores, migrations and backups
│   ├── evidence/     # Evidence ledger — claims, confidence, feedback
│   ├── explorer/     # Background exploration, grounding, cost/watermark
│   ├── kernel/       # Jobs, ledger, flags, metering — the supervision spine
│   ├── mcp/          # The MCP server and its doors
│   ├── ontology/     # Ontology builder, enricher, validator, store
│   ├── record/       # Inquiries, decisions, missions, claims, corrections
│   ├── routers/      # FastAPI domain routers (async, SSE)
│   ├── security/     # SQL safety gate, auth, credentials, audit
│   ├── semantic/     # Glossary, metrics, compiler, canonical resolver
│   ├── sheets/       # Spreadsheets — sources, the edit layer, views, sharing
│   ├── sql/          # SqlWriter, shared safety pipeline, guards
│   ├── tools/        # schema-linker, data catalog, profiler, stats
│   └── …             # 67 packages in all
├── evals/            # golden-set, Spider 2 and ablation harnesses
├── web/              # Next.js app — components, lib, design tokens
├── docs/             # architecture, roadmaps, audits
└── tests/            # pytest suite — hermetic, offline, failure-path + chaos
```

## Configuration

`.env` at the repository root; [`.env.example`](.env.example) is the full reference. Essentials:

| Variable | Default | What it does |
|---|---|---|
| `AUGHOR_BACKEND` | `ollama` | `ollama` \| `lmstudio` \| `groq` \| `together` \| `anthropic` \| `gemini` \| `openrouter` |
| `AUGHOR_CODER_MODEL` / `AUGHOR_NARRATOR_MODEL` | — | Per-role models (Settings → Models overrides env) |
| `AUGHOR_FALLBACK_BACKENDS` | Settings choice | Pin the failover chain order (`none` disables it) |
| `AUGHOR_DEFAULT_POSTGRES_DSN` | — | Pre-loads a Postgres connection on startup |
| `AUGHOR_QDRANT_PATH` | `qdrant/` in the state directory | Embedded vector store for semantic search (`semantic` extra) — in-process, no server |
| `AUGHOR_QDRANT_URL` | — | Set to pin a Qdrant *server* instead of the embedded store (e.g. `http://localhost:6333`) |
| `AUGHOR_PUBLIC_API_URL` | — | This API's public HTTPS origin, when it has one. It turns a Slack install into a button (the OAuth callback), gives a Teams bot its messaging endpoint, and puts absolute URLs on an agent's doors and A2A card. Unset, those say what is missing instead of guessing. |
| `AUGHOR_MODEL_PRICES` | — | Rates for a provider whose API publishes none, so spend tiles say a number instead of **unpriced**: `provider:model=input/output@date`, USD per 1M tokens, `;`-separated. Google publishes no price endpoint; for the default install's model the list price carried by the aggregators on 2026-09-15 was `gemini:gemini-3.1-flash-lite=0.25/1.50@2026-09-15` — re-check it, the date is part of the claim. A declared rate outranks the catalogue; the product itself ships no model id. |

**No feature flags.** Everything Aughor does is part of the platform and on. The only switches are
four choices an organisation's admin makes in **Settings ▸ Organization ▸ What Aughor may do** — share
summary statistics with other installs, send row text to an outside model, ask for a reason before a
run's details are read, let Aughor run model work on its own schedule — each off by default.

**Before exposing Aughor beyond `localhost`,** read [SECURITY.md](SECURITY.md) — the defaults assume a trusted single-user machine (`AUGHOR_API_KEY` gates requests when set; `AUGHOR_CORS_ORIGINS` scopes browsers; `AUGHOR_SECRET_KEY` encrypts stored credentials).

### Optional extras

```bash
uv sync --all-extras                      # everything (recommended for development)
uv sync --extra export --extra semantic   # or pick individually
uv sync                                   # serving core only
```

Each `uv sync` leaves exactly the extras it names and removes any others — so name every extra you want in one command. The installer syncs them all.

| Extra | Adds | Without it |
|---|---|---|
| `export` | PDF / PowerPoint reports | Export answers **501**, naming the extra |
| `semantic` | Semantic search over past analyses (embedded Qdrant — no server needed) | Reads return no hits, writes no-op |
| `fastread` | Faster bulk table reads (polars) | Falls back to DuckDB automatically |
| `warehouse` | Snowflake, BigQuery, MySQL, Exasol, Trino | Those connectors are unavailable |
| `crm`, `cloud-storage`, `knowledge-sync` | Stripe/HubSpot/Salesforce, Azure Blob, Confluence/Notion | Those connectors are unavailable |
| `observability`, `evals` | OTel/Langfuse export, eval harnesses | Tracing and harnesses unavailable |

Every extra degrades with a message naming the install command, and a footprint test keeps heavy packages off the API's import path. Sizes drift with platform — measure rather than trust: `uv run python scripts/measure_footprint.py --compare`.

## Project status

**Alpha.** No tagged release; `main` is the only supported branch.

What is real today: **15,000+ backend tests**, run by CI on Python 3.11 for every change and on 3.11–3.13 weekly; `ruff` at a zero baseline; CI additionally gates codegen drift for the typed API client. The frontend typechecks under `strict`, and CI runs six focused lint gates, two bundle-drift checks and a production build; its **2,900+ vitest tests** (pure-logic and jsdom component projects) run locally, not in CI. What is not: `eslint` reports pre-existing findings and is not a CI gate; there is no container image (`docker-compose.yml` brings up Qdrant, MLflow and Jaeger); deployment beyond a local machine and a Vercel data plane is young.

## Roadmap, contributing, security

- **[ROADMAP.md](ROADMAP.md)** — prioritized backlog and shipped milestones · **[FEATURES.md](FEATURES.md)** — the living reference, by capability (mechanisms and files) · **[docs/PLATFORM_ARCHITECTURE.md](docs/PLATFORM_ARCHITECTURE.md)** — tenancy, catalog, and the control/data-plane split.
- Contributions welcome — start with **[CONTRIBUTING.md](CONTRIBUTING.md)** and **[AGENTS.md](AGENTS.md)**; the load-bearing conventions (no feature flags — a feature merges on, guards that ship with a test proving they fire, never raising a ratchet baseline) are documented there. [Code of Conduct](CODE_OF_CONDUCT.md) applies.
- Report vulnerabilities **privately** — see [SECURITY.md](SECURITY.md).

## Acknowledgements

[LangGraph](https://github.com/langchain-ai/langgraph) · [DuckDB](https://duckdb.org) · [SQLGlot](https://github.com/tobymao/sqlglot) · [FastAPI](https://fastapi.tiangolo.com) · [Next.js](https://nextjs.org) · [Vega-Lite](https://vega.github.io/vega-lite/) · [DM Sans](https://github.com/googlefonts/dm-fonts) (SIL OFL 1.1). The human-command surface is shaped by Palantir Foundry's AI FDE ideas; the trust-and-verification framing owes a debt to MotherDuck's writing on governed semantic layers.

## License

[Apache License 2.0](LICENSE). Redistributed third-party assets (the DM Sans font files) carry their own licenses — see [NOTICE](NOTICE).
