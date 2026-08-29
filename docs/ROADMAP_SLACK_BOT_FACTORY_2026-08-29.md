# RC-5 — Bot doors become records (the Slack bot factory)

**Status:** designed, not built — except step 5.0, which RC-2 delivered
(`a274728b`). Design fixed with the user 2026-08-29.
**Audience:** a conversation picking this up cold. Everything needed to build it
is in this file; no prior session context is assumed.
**Roadmap integration:** the one-paragraph bullet for
`docs/CHAT_FLOW_ROADMAP_2026-08-28.md` is at the bottom (§9). Add it to Track RC
after RC-4 and sequence it in the "Sequencing" section at the end of that file.

---

## 1. Why this wave exists

RC-1 put `@aughor` in Slack. RC-2 gave its answers progress cards, charts, tables
and a deep link. Both shipped against **one** bot — and RC-1..RC-4 are all written
with "the Slack bot" in the singular.

The user's actual requirement (stated 2026-08-29):

> Users create **as many Slack bots as they want, from inside Aughor**, and reach
> each one two ways: `@mention` in Slack, or a regular/periodic trigger from the
> platform.

Nothing in the current build can do that. Not because the hard parts are missing —
they aren't — but because of one sentence:

> **The Slack app is an `.env.local` on a laptop, not a platform record.**
> One app, one process, one socket, one connection id, three tokens typed by hand.

Every gap in this wave is downstream of that.

### Not what the reference implementation does

The user raised VoltAgent's trigger model as prior art. Its
`createTriggers((on) => on.slack.messagePosted(...))` is **code-time**: you write
TypeScript, redeploy a process, and get one agent with hardcoded instructions.
Aughor needs **runtime** — a user clicks "New Slack bot" and has one, no deploy.
That difference is the whole reason the bot must be a *record the platform reads*
rather than a *code path someone ships*.

## 2. Premise, measured before designing

Verify these still hold before building — each was checked on `main` @ `4b8cdf1f`
plus the uncommitted RC-2 work.

| Capability | Where it already lives | State |
|---|---|---|
| A governed answer **as a named agent** | `POST /ask`, `agent_id` field — `aughor/routers/investigations.py:836` | ✅ works |
| Mention in → streamed answer out, threaded | `bots/slack/src/bot.ts`, `aughor.ts` | ✅ live receipt 2026-08-29 |
| Thread **is** the conversation | `session_id = thread.id` (FL-6) | ✅ works |
| Progress cards, charts, tables, deep link | `bots/slack/src/{progress,chart,artifacts}.ts`, `aughor/routers/charts.py` | ✅ RC-2 |
| Headless turns filed server-side | `_stream_converse` — `aughor/routers/investigations.py` | ✅ RC-2 (was the blocker) |
| Periodic trigger → agent run | `Condition(kind="schedule", cron)` → `Effect(kind="investigate", agent_id)` — `aughor/automations/models.py` | ✅ works |
| Secret at rest | `aughor/secretvault.py` — Fernet, mask-on-read, idempotent encrypt | ✅ already holds webhook URLs |
| Outbound Slack | `aughor/notifications/executor.py:143` — incoming **webhook** | ⚠️ wrong identity, see step 5.4 |

**The brain is not the gap.** `/ask` already takes `agent_id`; `buildBot()` already
takes `ask` as a parameter and knows nothing about which agent it speaks for. A
Slack bot **is** a stored tuple:

```
{bot_token, app_token, signing_secret}  →  {agent_id, connection_id}
```

No second brain, no second prompt path, no second tenancy story. This is the same
discipline `Effect` follows in the automation plane — *a reference, never a new
action type*.

## 3. The decision: one Slack app per bot, created by manifest paste

Three routes were weighed with the user. The column that decided it is the last.

| Route | Cost | Bots per Slack app |
|---|---|---|
| **A. Manifest paste** ← **CHOSEN** | none; ships today | 1:1 |
| B. Manifest API (`apps.manifest.create`) | user mints + rotates a configuration token — a new secret class for Aughor to hold | 1:1 |
| C. OAuth distribution ("Add to Slack") | Aughor becomes a distributed Slack app | **N bots inside 1 app** |

C is one click, but then every bot is `@Aughor` and users disambiguate by channel
or prefix rather than by name. The ask was explicitly *"as many slack apps/bots"* —
distinct Slack identities (`@salesbot`, `@finance-bot`). A and B deliver that; C
does not. B was declined: fewer clicks, but Aughor would hold a rotating
configuration token, and bot-count-per-user is not yet proven high enough to earn
that.

**Build the record so identity is a FIELD, not an assumption** — C must stay
reachable later without re-architecting.

### The trap RC-1 already paid for
Render the manifest as **JSON**. Slack's YAML tab produced a "can't translate"
error during RC-1's live setup and cost real time.

### The manifest Aughor renders

```json
{
  "display_information": { "name": "<bot name>", "description": "<agent purpose>" },
  "features": {
    "bot_user": { "display_name": "<bot name>", "always_online": true },
    "app_home": { "messages_tab_enabled": true, "messages_tab_read_only_enabled": false }
  },
  "oauth_config": { "scopes": { "bot": [
    "app_mentions:read", "chat:write", "channels:history",
    "groups:history", "im:history", "im:write", "files:write"
  ] } },
  "settings": {
    "event_subscriptions": { "bot_events": ["app_mention", "message.im"] },
    "socket_mode_enabled": true
  }
}
```

- `files:write` is required by RC-2's chart PNG and CSV uploads. Grant it at
  creation — far cheaper than making every user re-authorize an installed app.
- Socket Mode is deliberate and inherited from RC-1: it connects **out**, so a
  user's bot needs no public URL, tunnel, or webhook endpoint. This is what lets a
  self-hosted Aughor run bots at all.
- If `SLACK_AGENT_VIEW=1` is to be supported per-bot (RC-2 added the flag, and the
  Slack adapter's `agentView` requires the app be in `agent_view` mode), the
  manifest must declare the agent feature **and** the record must carry the
  matching boolean. Mismatched, `stopStream` sends a parameter the app cannot
  accept and every answer loses its final message.

## 4. The object

```
SlackBot
  id, name, enabled
  agent_id         → UserAgent   (whose instructions/docs/packs answer)
  connection_id    → which warehouse it answers over
  bot_token        ┐
  app_token        ├ secretvault: encrypted at rest, masked on read
  signing_secret   ┘
  agent_view       bool  (must match the manifest; see §3)
  team_id, slack_app_id, installed_at
```

**Do not put instructions on this record.** A bot points at a `UserAgent`
(`aughor/custom_agents/models.py`), which already owns instructions, purpose,
bound documents, packs, connection and its eval chip. Duplicating any of it here
forks the governing configuration and silently invalidates `config_rev` — the
fingerprint the pass chip depends on to say whether a measurement is still about
this agent.

---

## 5. The steps

Build in order. **5.0 is already done** (RC-2) — its entry stays so the
dependency is legible. 5.1–5.3 are the factory; 5.4 is the half that makes this
more than an inbox.

### Step 5.0 — File turns server-side ✅ **DONE** (RC-2, `a274728b`)

**Was the prerequisite; is now satisfied.** Kept here because the next four steps
depend on it and a reader needs to know it holds.

`_stream_converse` never filed turns server-side — the web client filed them
client-side. A converse turn that called no tool (the "are you sure?", the
follow-up answered from context or the briefing) wrote nothing at all. Invisible
on the web, a hole on every other door: Slack keeps no client-side copy, so a
conversation lost exactly the follow-ups that made it a conversation, and the next
turn rebuilt history from a record missing the one before it. Found live in a
thread (chip `task_17fc91f9`).

Fixed in RC-2: `_stream_converse` files the exchange when nothing else did —
only when `turn["inv_id"]` is empty, never in addition, so one exchange is never
two rows. Best-effort, counter `converse.file_turn`.

**Receipt banked.** `tests/unit/test_converse_files_turn.py` drives the real
`_stream_converse` against a stubbed `converse()` and reads history back, so it
fails if the filing is removed **or** written where the conversation cannot see it.

### Step 5.1 — The `SlackBot` record

**Goal.** Persist the tuple from §4.

**Do.**
- `aughor/slackbots/models.py` — the pydantic model, plus `to_safe_dict()`
  returning `mask_secret(...)` for all three tokens. Copy the mask/round-trip
  convention from `ActionTrigger.to_safe_dict` in
  `aughor/notifications/models.py`: the API shows the mask, the frontend sends the
  mask back unchanged on save, and the update path detects it and keeps the stored
  secret.
- `aughor/slackbots/store.py` — use **`LedgerListStore`**
  (`aughor/util/json_store.py:254`), the same store
  `aughor/notifications/store.py` uses for triggers, with an
  `AUGHOR_SLACKBOTS_DIR` env override for test isolation.
- `aughor/routers/slackbots.py` — CRUD; register in `aughor/api.py` alongside the
  other `app.include_router(...)` calls (~line 762).
- Add the route to `aughor/rbac/policy.py` with an appropriate permission.

**Why `LedgerListStore` and not a SQLite table.** A bot record is *delivery
configuration another instance must see*. The file-backed store is what made a
brief subscription "created" on Vercel evaporate with the response, so every cron
tick evaluated zero briefs — the Ledger store exists precisely for this class.
It also means **no migration**, which dodges the migration-numbering trap
(`PRAGMA user_version` must be read off the LIVE db before numbering; hermetic
tests cannot catch a wrong number) entirely.

**Receipt.** Two bots stored; `GET` returns masked tokens; a save that echoes the
mask back does not overwrite the real secret and does not double-encrypt
(`encrypt_secret` is idempotent, but the mask path must be proven separately).

### Step 5.2 — Manifest render + guided creation

**Goal.** A user creates a bot without touching a file.

**Do.**
- `GET /slack/bots/manifest?agent_id=…` renders the §3 JSON, named and described
  from the bound `UserAgent` (`name`, `purpose`).
- A guided UI: **render manifest → user pastes it at
  `api.slack.com/apps?new_app=1` → installs to the workspace → pastes back the
  three tokens** → Aughor calls Slack `auth.test` to verify and capture `team_id`
  and the bot's own user id before storing `enabled=true`.
- Verify before store. A bot stored with a bad token is a socket that fails to
  open at 03:00 with nobody watching.

**Receipt.** A user creates a **second** bot end-to-end, from the UI, without
editing `.env.local` or restarting anything.

### Step 5.3 — Registry-driven supervisor

**Goal.** One process, N sockets. Socket Mode is per app token — each Slack app
opens its own WebSocket — so the process must fan out.

**Do.** Replace the env-reading `bots/slack/src/index.ts` with a supervisor:

```
GET /slack/bots  →  [{id, agent_id, connection_id, tokens…, agent_view}, …]
                 →  one Chat instance per enabled row
                 →  each posts to /ask with ITS agent_id and connection_id
```

- `buildBot({ask, renderChart, adapters, state, webUrl})` is already a factory, so
  this is factory-per-row plus reconciliation: open new rows, close removed rows,
  restart a row whose tokens or `agent_view` changed.
- `createAskStream()` currently closes over `AUGHOR_CONNECTION_ID` from env
  (`bots/slack/src/aughor.ts:71`). It must take `{agentId, connectionId}` per bot
  and send `agent_id` in the `/ask` body.
- Keep the tokens in memory only; the supervisor fetches them over HTTP.

**Receipt.** Two bots answer in one workspace, each as its own agent — proven by
asking both the *same* question and getting answers that differ in a way only
their differing agent bindings explain.

**Trap.** The supervisor must read the registry **over HTTP**, never by opening
`data/system.db`. A second process touching that file is how it has been corrupted
four times.

### Step 5.4 — `Effect(kind="slack_post")` — the periodic trigger half

**Goal.** Close the loop the user asked for. The cron→agent path already exists;
what is missing is the **last hop**.

**The gap, precisely.** `Effect(kind="notify")` fires an ActionHub trigger, which
is an incoming **webhook** (`aughor/notifications/executor.py:143`). It posts as
the *webhook's* identity, into a channel, with no thread anyone can reply into. A
scheduled run therefore dead-ends on arrival. **The missing piece is identity, not
scheduling.**

**Do.** Add one effect kind to `aughor/automations/models.py`:

```
Effect(kind="slack_post", config={"bot_id": …, "channel": …})
```

Register it in `_EFFECT_REQUIRED` with `("bot_id", "channel")` so a malformed
automation is rejected at construction, not at execute — the plane's existing
rule. Deliver via the bot's `chat:write`, as the bot.

**Why this is the wave's payoff.**

> cron fires → the bot posts in-channel **as itself** → a user `@`-replies in that
> thread → `thread.id` is already the `session_id` → the follow-up composes on the
> same Aughor conversation, with the same agent, over the same connection.

That is the difference between a bot that notifies and one that behaves like a
colleague. It is also the first time a *scheduled* Aughor run becomes
conversational rather than terminal.

**Receipt.** A cron posts as the bot; an `@`-reply in that thread continues the
same conversation — proven by the reply's answer depending on the scheduled post's
content.

---

## 6. Slice/receipt summary

| # | Slice | Receipt |
|---|---|---|
| **5.0** ✅ | File turns server-side in `_stream_converse` | **Banked** — `tests/unit/test_converse_files_turn.py` |
| **5.1** | `SlackBot` record + `LedgerListStore` + CRUD routes, tokens vaulted | Two bots stored; `GET` shows masks; mask round-trip preserves the secret |
| **5.2** | Manifest render + guided create (`auth.test` verify) | A user creates a **second** bot end-to-end without touching a file |
| **5.3** | Registry-driven supervisor, N sockets, reconcile on change | Two bots answer in one workspace, each as its own agent, proven by differing answers |
| **5.4** | `Effect(kind="slack_post")` | Cron posts as the bot; an `@`-reply threads back onto the same conversation |

## 7. Traps that span the wave

1. **Check what has landed before assuming this doc is current.** RC-2 was built
   in parallel *while this wave was being designed* and committed to
   `claude/rc2-slack-investigation-streaming` as `a274728b` — it moved step 5.0
   from "to build" to "done" between two readings of this file. Step 5.3 rewrites
   `bots/slack/src/index.ts`, which RC-2 also changed (it gained
   `SLACK_AGENT_VIEW` and `AUGHOR_WEB_URL`); branch from a base that contains
   RC-2, and re-read `index.ts` rather than trusting the shape quoted here. Never
   tree-wide-revert a tree that may carry another conversation's work
   (`git reset --hard`, bare `git stash`, `git checkout <file>` — which restores
   from the *index* and silently wipes unstaged edits).
2. **Slack rate limits are per workspace, not per app.** N bots in one workspace
   share the ceiling. The streaming path is post-then-edit, so `chat.update` is
   the hottest call and the first to throttle. Bot count is not free.
3. **Approvals are stored per task** — a scheduled bot's first run prompts and
   stalls silently at 03:00. RC-3 (durable approval cards) is the real fix; until
   then a `slack_post` automation must pre-authorize.
4. **One writer per `data/`** — see step 5.3.
5. **Provider caps are per model, per minute.** Gemini's free tier is 15 RPM; a
   handful of bots answering at once bursts past it and the failover chain
   silently answers from a paid backend while the banner still claims otherwise
   (open chip `task_ff50f298`).
6. **`flag_enabled()` returns False for unregistered names** — indistinguishable
   from "off". If any slice lands behind a flag, register it properly.

## 8. What this wave is NOT

- **Not a second agent runtime.** Python keeps the loop, guards, tenancy and
  metering. The TypeScript process carries bytes and nothing else — RC-1's
  discipline, held.
- **Not per-bot instructions.** See §4.
- **Not a webhook migration.** `notify`/ActionHub keeps working for alerting. Bot
  identity is additive, for the conversational path.
- **Not OAuth distribution.** Route C stays available later; §3 explains the cost
  of choosing it now.

## 9. Bullet for the roadmap

Already added to Track RC in `docs/CHAT_FLOW_ROADMAP_2026-08-28.md`, after RC-4,
as the bullet below. **Sequencing is deliberately left open**: that file's
"Sequencing" line is marked user-decided, so where RC-5 falls against RC-2..RC-4
is the user's call, not a conversation's.

> - **RC-5 — Bot doors become records** (design fixed 2026-08-29, user-decided):
>   a Slack bot is a stored `{credentials} → {agent_id, connection_id}` binding,
>   not an `.env.local`; users create as many as they want via a rendered manifest
>   (one Slack app per bot — route A of three; JSON, never the YAML tab), a
>   registry-driven supervisor runs N sockets in one process, and a new
>   `Effect(kind="slack_post")` lets a cron post AS the bot so the `@`-reply
>   threads back onto the same conversation. Its one prerequisite — headless
>   doors leaving holes in their own conversations, because `_stream_converse`
>   never filed turns server-side — was **closed by RC-2** (`a274728b`, chip
>   `task_17fc91f9`), so the factory is unblocked. Full spec, with steps and
>   receipts:
>   `docs/ROADMAP_SLACK_BOT_FACTORY_2026-08-29.md`.
