# Aughor × Nous Hermes Agent — Integration Architecture

## The Core Idea

Our Aughor is the **analytical engine** — it investigates business questions, runs SQL, scores evidence, and produces structured reports. Nous Hermes Agent is the **operating layer** — it schedules work, accumulates memory across sessions, communicates across channels, learns from patterns, and orchestrates a multi-agent hierarchy.

Neither replaces the other. Aughor does the deep analytical thinking. Nous Hermes Agent is the nervous system that surrounds it.

---

## How They Connect: The MCP Bridge

Every integration in this architecture flows through a single foundational piece: **Aughor exposed as an MCP server**.

Nous Hermes Agent supports bidirectional MCP — it can consume tools from any MCP-compatible server, and each tool becomes callable as `mcp_<server_name>_<tool_name>` natively in any agent session. Once Aughor is an MCP server, every Nous Hermes Agent instance in the hierarchy — org level and analyst level alike — can invoke investigations, read history, and update the semantic layer as naturally as calling any other tool.

**MCP tools Aughor exposes:**

| Tool | What it does |
|---|---|
| `aughor_investigate` | Submit a question, get back a full investigation (SSE or polling) |
| `aughor_get_investigation` | Fetch a completed investigation by ID — full report, hypotheses, SQL citations |
| `aughor_search_investigations` | Semantic search across all past investigations (Prior Analyses RAG) |
| `aughor_list_investigations` | Browse history with status, headline, timestamp |
| `aughor_get_schema` | Return the annotated schema for a connection (with glossary enrichment) |
| `aughor_update_glossary` | Write a table or column annotation back into the semantic layer |
| `aughor_submit_feedback` | Resume a paused HITL investigation with analyst context |
| `aughor_reindex` | Trigger a Qdrant reindex of all completed investigations |

This is the only infrastructure piece that needs to be built. Everything else in this document is configuration, SOUL.md writing, and skills authoring.

---

## The Three-Layer Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        LAYER 1 — ORG AGENT                               │
│                   (one instance, always-on, server-deployed)             │
│                                                                          │
│  Responsibilities:                                                       │
│  • Scheduled sweeps of all critical KPIs                                │
│  • Accumulates and compresses org-wide analytical knowledge              │
│  • Detects cross-analyst patterns, confirms glossary corrections         │
│  • Publishes shared intelligence downward to analyst agents              │
│  • Receives incremental findings upward from analyst agents              │
│  • Collects HITL trajectories for RL training                            │
│  • Full access to all Aughor connections                                 │
│                                                                          │
│  Tools: aughor_investigate, aughor_update_glossary, aughor_reindex,      │
│         aughor_search_investigations, aughor_list_investigations         │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │
              shared AGENTS.md (org knowledge snapshot)
              updated by org agent after each sweep cycle
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  ANALYST      │   │  ANALYST      │   │  ANALYST      │
│  AGENT        │   │  AGENT        │   │  AGENT        │
│  Finance      │   │  Product      │   │  Growth       │
│               │   │               │   │               │
│  SOUL.md:     │   │  SOUL.md:     │   │  SOUL.md:     │
│  finance lens │   │  product lens │   │  growth lens  │
│               │   │               │   │               │
│  Delivers to: │   │  Delivers to: │   │  Delivers to: │
│  Slack #fin   │   │  Telegram DM  │   │  Email        │
│               │   │               │   │               │
│  Can:         │   │  Can:         │   │  Can:         │
│  investigate  │   │  investigate  │   │  investigate  │
│  submit HITL  │   │  submit HITL  │   │  submit HITL  │
│  flag glossary│   │  flag glossary│   │  flag glossary│
│               │   │               │   │               │
│  Cannot:      │   │  Cannot:      │   │  Cannot:      │
│  modify code  │   │  modify code  │   │  modify code  │
│  confirm gloss│   │  confirm gloss│   │  confirm gloss│
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                    ┌───────▼───────┐
                    │    LAYER 3    │
                    │    HERMES     │
                    │  (MCP Server) │
                    │               │
                    │  LangGraph    │
                    │  investigative│
                    │  loop         │
                    │  + semantic   │
                    │  layer        │
                    │  + history    │
                    │  + HITL       │
                    └───────────────┘
```

---

## Layer 1 — Org Agent

### Identity

The org agent is configured via `SOUL.md`:

```markdown
You are the analytical backbone of this organisation.
You do not answer ad-hoc questions. Your job is continuous:
scan, detect, accumulate, and broadcast.

You have full access to all data connections via the Aughor
investigation tool. You are the only agent authorised to
confirm glossary changes and trigger reindexing.

You communicate only with analyst agents (via shared AGENTS.md
and direct delegation) and with the investigation engine.
You do not interact with humans directly.
```

### Scheduled Sweeps

Using `aughor cron` with natural language scheduling:

```
Every Monday 06:00 — Run investigations on: revenue by region vs last 4 weeks,
payment failure rate by gateway, top 3 anomalies in orders.
Save outputs to sweep_YYYY-MM-DD.md. Deliver summary to #data-pulse Slack.

Every day 07:00 — Run watchdog: check if any KPI has moved >2σ from 30-day
baseline. If triggered, run full investigation and deliver to #alerts.
[no_agent=True for the threshold check; agent mode only on trigger]

Every Sunday 22:00 — Run memory refinement: read all sweep outputs from
the past week, compress into org knowledge snapshot, update shared AGENTS.md.
```

The `context_from` job chaining parameter enables multi-stage pipelines — the Monday KPI sweep's output is automatically prepended as context for the Sunday memory refinement job, so the compressor always has the freshest raw data without being re-told what to look at.

### Memory Architecture

The org agent maintains two memory layers:

**MEMORY.md (2,200 char limit — compressed, high-signal)**
The LLM continuously overwrites this with the most load-bearing current knowledge:
```
- APAC revenue: seasonally soft Q1/Q3, do not flag <5% drops as anomalies
- payment_gateway_fee column: named misleadingly — includes interchange, not just gateway
- orders.freight_value: NULL for ~8% of rows (legacy import pre-2023), exclude from averages
- Black Friday / Cyber Monday: always exclude Nov 23-30 window from baseline comparisons
- product_category_name: Portuguese in raw table — glossary has English mappings
```

**External memory provider (Mem0 or Honcho)**
Unlimited, structured, semantically searchable. Stores every sweep output, every confirmed correction, every analyst flag. The MEMORY.md is a compressed front-cache of this; the external provider is the full archive.

### Pattern Detection and Glossary Confirmation

The org agent runs `aughor insights` against accumulated sessions at the end of each week. When the same glossary issue is flagged by two or more analyst agents independently, the org agent:

1. Searches `aughor_search_investigations` to confirm the pattern appears in multiple investigations
2. Calls `aughor_update_glossary` with the corrected description
3. Calls `aughor_reindex` to propagate the correction into the Qdrant schema index
4. Updates MEMORY.md and the shared AGENTS.md knowledge snapshot

This is the only path to confirmed glossary changes. Analyst agents flag; the org agent confirms.

### Publishing Intelligence Downward

After each sweep cycle, the org agent rewrites a shared `AGENTS.md` file in a directory mounted by all analyst agents. Format:

```markdown
# Org Intelligence Snapshot — 2026-05-15

## Active Patterns
- APAC revenue soft Jan–Mar every year (seasonal, not anomaly)
- Payment failures spike Friday 18:00–20:00 UTC — known gateway maintenance window

## Confirmed Glossary Updates This Week
- orders.freight_value: now annotated with NULL caveat
- payment_gateway_fee: renamed description to clarify it includes interchange

## Open Flags (unconfirmed, use with caution)
- [growth-agent, 2026-05-13] product_views.session_id may double-count mobile refreshes

## Investigations Worth Reading
- inv_id: a3f9c12 — APAC Q1 root cause, confirmed seasonal pattern (score: 0.94)
- inv_id: b7e2a45 — Payment failure analysis, gateway window confirmed
```

Every analyst agent loads this as a context file at session start via progressive directory discovery.

---

## Layer 2 — Analyst Agent Swarm

### Identity Per Domain

Each analyst agent has its own `SOUL.md`. Three examples:

**Finance analyst agent:**
```markdown
You are a finance-focused analyst agent.
Before every investigation, check the org intelligence snapshot for
relevant patterns. Always note if a finding is already documented there.

When you discover a data issue or a description that seems wrong,
flag it explicitly with: FLAG_FOR_ORG: <table>.<column> — <what you observed>
Do not update the glossary yourself.

Deliver all reports to the #finance-insights Slack channel
unless the user requests otherwise.
```

**Product analyst agent:**
```markdown
You are a product analyst agent. You think in funnels,
retention curves, and feature adoption.
[...domain-specific framing...]
Deliver to Telegram DM unless a channel is specified.
FLAG_FOR_ORG pattern applies — you observe, org agent confirms.
```

**Growth analyst agent:**
```markdown
You are a growth analyst agent. You think in acquisition,
activation, and revenue expansion.
[...domain-specific framing...]
Deliver to email unless otherwise requested.
```

### What Analyst Agents Can Do

**Trigger investigations:**
```
User: "Why did trial conversions drop this week?"
Agent: [calls mcp_aughor_investigate with the question]
       [streams back hypothesis cards, evidence, report]
       [delivers to configured channel]
```

**Use HITL as a domain bridge:**
The analyst agent is itself a domain expert proxy. When Aughor pauses for HITL feedback, the analyst agent prepares the feedback using its SOUL.md domain lens — e.g. the finance agent knows that a revenue drop in the last week of the quarter is likely a booking timing artifact, not a real decline. It calls `aughor_submit_feedback` with that context before the user even needs to type it.

In practice: the agent presents the paused hypothesis verdicts to the analyst, offers a domain-informed interpretation, and either sends it automatically (if confidence is high from SOUL.md + org snapshot) or asks the analyst to confirm before submitting.

**Flag glossary issues:**
Analyst agents are instructed via SOUL.md to emit `FLAG_FOR_ORG:` markers whenever they observe a description mismatch. A hook captures these:

```yaml
# ~/.aughor/hooks/flag_capture/HOOK.yaml
event: message_sent
filter: "FLAG_FOR_ORG:"
handler: flag_capture/handler.py
```

```python
# handler.py — fires on every message containing FLAG_FOR_ORG:
# Extracts the flag, appends it to a shared flags.jsonl file
# Org agent reads this file during its weekly pattern detection cycle
```

**Build investigation skills over time:**
When an analyst triggers the same type of investigation repeatedly (e.g. "weekly cohort retention drop analysis"), the pattern can be crystallised into a Nous Hermes skill:

```markdown
---
name: weekly-retention-analysis
description: Investigate cohort retention drops week-over-week
---
Use aughor_investigate with: "Why did [COHORT] retention drop in the week of [DATE]?
Focus on activation steps, not acquisition. Compare to 4-week baseline."
Check org snapshot for known seasonal patterns before concluding.
Deliver to #product-retention.
```

Once created, any analyst agent can run `/skills weekly-retention-analysis` and the investigation runs with all accumulated context baked in.

### What Analyst Agents Cannot Do

- Confirm or apply glossary changes (no `aughor_update_glossary` permission — org agent only)
- Modify any code, prompts, or graph configuration
- Trigger `aughor_reindex` (org agent only)
- Access connections outside their assigned scope (enforced via MCP tool filtering in config)

These constraints are enforced at the Nous Hermes Agent config level via per-server tool filtering:

```yaml
# analyst agent config.yaml
mcp_servers:
  aughor:
    url: http://aughor-server:8000/mcp
    allowed_tools:
      - aughor_investigate
      - aughor_get_investigation
      - aughor_search_investigations
      - aughor_submit_feedback
      # aughor_update_glossary — NOT listed, not callable
      # aughor_reindex — NOT listed, not callable
```

---

## The Learning Loop

This is where the architecture earns its compound returns. Each cycle makes the next cycle cheaper, faster, and more accurate.

```
┌─────────────────────────────────────────────────────────────────────┐
│                      WEEKLY LEARNING CYCLE                          │
│                                                                     │
│  1. Analyst agents run investigations (on-demand + scheduled)       │
│     └─► Each HITL run logs: (question, verdicts, feedback, report) │
│                                                                     │
│  2. Analyst agents emit FLAG_FOR_ORG markers when they spot issues │
│     └─► Hook captures to shared flags.jsonl                        │
│                                                                     │
│  3. Org agent Sunday sweep reads:                                   │
│     ├─ All sweep outputs from the week (via context_from chaining) │
│     ├─ flags.jsonl (analyst observations)                          │
│     ├─ aughor_list_investigations (what ran, what completed)       │
│     └─ aughor insights (session pattern extraction)               │
│                                                                     │
│  4. Org agent identifies confirmed patterns (≥2 independent flags) │
│     └─► aughor_update_glossary for each confirmed correction       │
│     └─► aughor_reindex to propagate into Qdrant                    │
│                                                                     │
│  5. Org agent rewrites shared AGENTS.md knowledge snapshot         │
│     └─► All analyst agents load this fresh at next session start   │
│                                                                     │
│  6. MEMORY.md recompressed by org agent                            │
│     └─► High-signal facts, confirmed patterns, seasonal markers    │
│                                                                     │
│  7. HITL trajectories batched → RL training input                  │
│     └─► (question, evidence, feedback, report) tuples              │
│     └─► Fine-tunes the underlying coder/narrator models            │
│         on your specific data domain over time                     │
└─────────────────────────────────────────────────────────────────────┘
```

**What improves each cycle:**
- Aughor's glossary gets richer → SQL generation gets more accurate → fewer self-corrections → faster investigations
- Org agent's MEMORY.md gets denser → analyst agents skip known patterns → fewer redundant investigations → Prior Analyses RAG cache hit rate increases
- HITL trajectories accumulate → RL training → coder/narrator models improve on your domain → HITL needed less often
- Analyst skills library grows → common investigation types run in one command with all context pre-loaded

---

## Delivery and Notification Layer

Every output from the investigation engine reaches analysts where they already work.

**Org agent → team channels:**
```
aughor cron: "Every Monday 08:00, deliver weekly KPI sweep summary to
#data-pulse Slack. Flag any >2σ anomalies in bold."
```

**Analyst agent → individual channels:**
- Finance agent → `#finance-insights` Slack
- Product agent → analyst's Telegram DM
- Growth agent → analyst's email

**Alert mode (watchdog pattern):**
```
aughor cron: daily 07:00, no_agent=True
Script: query Aughor for last 24h anomalies
        empty output → silent tick
        anomaly found → trigger aughor_investigate → deliver to #alerts
```

This uses Nous Hermes Agent's `no_agent=True` cron mode — a lightweight watchdog check runs with no LLM overhead; the full investigation agent fires only when the threshold is crossed.

**Voice delivery (optional):**
Analyst agents configured with TTS providers can deliver report summaries as voice messages on Telegram — useful for executives who want a 30-second audio briefing rather than a full written report.

---

## What Gets Built

In order of dependency:

| # | What | Where | Unlocks |
|---|---|---|---|
| 1 | MCP server wrapper around Aughor FastAPI | `aughor/mcp_server.py` | Everything — the foundational piece |
| 2 | Org agent SOUL.md + config + cron jobs | Nous Aughor config files | Scheduled sweeps, org memory accumulation |
| 3 | Analyst agent SOUL.md templates (per domain) | Nous Hermes config files | On-demand investigations, HITL proxy, channel delivery |
| 4 | FLAG_FOR_ORG hook (HOOK.yaml + handler.py) | `~/.aughor/hooks/` | Analyst → org agent correction flow |
| 5 | Shared AGENTS.md schema + publish script | Shared filesystem or Git | Intelligence flowing downward to analyst agents |
| 6 | Analyst permission filter in config.yaml | Analyst agent configs | Enforces what analyst agents can/cannot call |
| 7 | Investigation skills library | `~/.aughor/skills/` | One-command common investigation patterns |
| 8 | RL trajectory logger | Hook on `aughor_submit_feedback` | Fine-tuning pipeline |

The MCP server (item 1) is the only item that requires writing Python code inside this repo. Everything else is configuration, YAML, and SOUL.md authoring inside the Nous Hermes Agent setup.

---

## What This Looks Like in Practice

**Monday morning, 08:00:**
The org agent's cron job fires. It calls `aughor_investigate` three times across the company's critical KPIs. Job chaining means each investigation's output is context for the synthesis step. The compressed summary lands in `#data-pulse` on Slack by 08:30. The finance analyst sees it, clicks into the full report via a link in the message. Nothing was manually triggered.

**A finance analyst asks a follow-up:**
She messages the finance agent on Slack: *"Why is APAC below target again?"* The finance agent checks the org AGENTS.md snapshot — sees the note that APAC is seasonally soft Q1/Q3. It calls `aughor_investigate` with that context pre-loaded via the HITL feedback mechanism. The report comes back in 4 minutes, confirms seasonal pattern, cites the prior investigation from six weeks ago.

**A new data issue is discovered:**
The product analyst agent runs an investigation and notices `session_id` seems to double-count mobile refreshes. It emits `FLAG_FOR_ORG: events.session_id — may double-count mobile refresh events`. The hook captures this to `flags.jsonl`. The growth analyst hits the same issue two days later — another flag. Sunday: the org agent sees two independent flags on the same column, verifies by running a targeted investigation, confirms the issue, calls `aughor_update_glossary`, triggers reindex. The following Monday, every analyst agent's investigations automatically account for this.

**Six months in:**
The org agent's MEMORY.md reads like a seasoned analyst's mental model of the company's data — seasonal patterns, known caveats, glossary corrections, past root causes. The Qdrant prior-investigations index has hundreds of completed investigations with high cache-hit rates. The skills library has 20+ crystallised investigation patterns. The coder model has been fine-tuned three times on domain-specific HITL trajectories. New analyst agents onboard instantly — they load the shared AGENTS.md on first session and immediately have six months of institutional knowledge.

---

*This document describes the integration architecture between Aughor (autonomous data analyst) and Nous Hermes Agent (multi-agent operating layer). Implementation starts with the MCP server wrapper — see `ROADMAP.md` for sequencing.*
