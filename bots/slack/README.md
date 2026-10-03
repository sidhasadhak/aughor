# Aughor in Slack

A deliberately thin TypeScript transport that puts `@aughor` in a Slack thread.
The loop, the guards, tenancy and metering all stay in the Python API; this
process carries a question in and streams the governed answer — with its
progress, its chart and its table — back out.

```
@aughor why did revenue dip?
        │
        ├─ POST /ask (depth "auto", session_id = the Slack thread id)
        │     └─ SSE frames ──► prose (suffix-folded) + task cards
        ├─ POST /charts/svg ──► SVG ──► PNG (resvg, in-process)
        └─ the thread gets: the answer · the chart · the table or its CSV · a link back
```

## What it needs from your Slack app

**Since RC-5 the app is made from the manifest Aughor renders** (`GET
/slack-bots/manifest`, or the Slack door on an agent's Create flow / Integrations
→ Slack), and since AO-2c that manifest is complete: agent mode (Slack's Agents &
AI Apps — the legacy assistant view closed to new apps on 2026-08-20 and retires
in February 2027), every scope below, Socket Mode, and the agent-mode events. An
app made from it needs none of the hand steps that used to follow. With one
configuration token (AO-2d) Aughor creates the app in Slack itself; what stays
by hand is the install (a button on an HTTPS deployment) and the app-level
token, which Slack offers no API for.

The surfaces, and what each needs — all of it in the rendered manifest:

| Surface | Needs | Without it |
|---|---|---|
| Streamed answer, threading, follow-ups | the base scopes | works |
| Progress cards during a deep run | agent mode + `assistant:write` | silently absent; answer still arrives |
| Native stop button → server-side cancel | agent mode + `assistant:write` | no stop button exists |
| Chart PNG and CSV attachments | `files:write` | the upload fails; the inline table still posts |
| Inline table, deep link | the base scopes | works |

**Only for an app created before 2026-10-03 from the old manifest**, at
[api.slack.com/apps](https://api.slack.com/apps):

1. **OAuth & Permissions → Bot Token Scopes** — add `assistant:write` and
   `files:write` to what is already there.
2. **Agents & AI Apps** — enable it. This is one-way: Aughor's record follows
   (`agent_view`), and refuses to be switched back, because Slack will not.
3. **Event Subscriptions → Subscribe to bot events** — add `app_home_opened`,
   `app_context_changed`, `agent_session_stopped`, `agent_session_title_changed`
   alongside the existing `app_mention` and `message.*` events.
4. **Reinstall the app to the workspace.** Scope changes do not take effect
   until you do, and this is the step that is easy to skip.
5. Single-bot mode only (the three `SLACK_*` vars): set `SLACK_AGENT_VIEW=1` in
   `.env.local`. A bot read from Aughor's registry carries the mode on its record.

To check what the installed token actually has:

```bash
curl -sD- -o/dev/null -X POST https://slack.com/api/auth.test -H "Authorization: Bearer $SLACK_BOT_TOKEN" | grep -i x-oauth-scopes
```

## Configuration

Copy `.env.local.example` to `.env.local` and fill it in.

| Variable | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-…`, from OAuth & Permissions |
| `SLACK_APP_TOKEN` | `xapp-…` with `connections:write`, for Socket Mode |
| `SLACK_SIGNING_SECRET` | from Basic Information |
| `SLACK_AGENT_VIEW` | `1` once the app is in Agents & AI Apps mode. Left off, the adapter uses the legacy compatibility path. Turning it on against an app that is NOT in agent mode makes `stopStream` send a parameter that app cannot accept, which costs the final message of every answer — hence a flag, not a default. |
| `AUGHOR_API_URL` | defaults to `http://127.0.0.1:8000` |
| `AUGHOR_RUNTIME_KEY` | **required for the multi-bot supervisor.** `GET /slack-bots/runtime` is the one route that returns raw `xoxb-`/`xapp-` tokens, so it refuses an unauthenticated caller. Generate the key in the app — **Integrations → Slack → Supervisor key** — and paste the line it gives you here. Single-bot mode (the three `SLACK_*` vars above) does not read that route and needs no key. |
| `AUGHOR_API_KEY` | when the API requires one org-wide. It also satisfies the runtime route, so a deployment that already sets it needs no separate runtime key. |
| `AUGHOR_CONNECTION_ID` | which connection to answer from; defaults to `workspace` |
| `AUGHOR_WEB_URL` | where "Open in Aughor →" points. Unset, answers simply carry no link — a wrong host is worse than none. |
| `LOG_LEVEL` | `debug` shows every incoming envelope, and the adapter's own streaming decisions ("using fallback stream — …"). The difference between "Slack never sent the event" and "it arrived and nothing matched" is invisible at `info`. |

## Running

```bash
npm install
npm run dev
```

After every reconcile (30 s by default) the supervisor POSTs a heartbeat to
`/slack-bots/runtime/heartbeat` — which bots it has open, which failed to start, and
how often it reconciles — with the same key the registry read uses. That is what the
bot card in **Integrations → Slack** and the agent's Map read: *listening since …*
when a beat arrived within three reconcile intervals, otherwise *not listening* with
the command above. A heartbeat that cannot be delivered never stops a socket; the
process logs the change of state once and the card says so until it lands.

Socket Mode connects **out** to Slack over a WebSocket, so there is no public
URL, tunnel, or webhook endpoint to expose.

## Tests

```bash
npm test
```

Hermetic — no Slack workspace, no Aughor API. The seam test drives the real
Chat pipeline (mention detection, threading, post streaming) against a mock
adapter, so it fails if the handler is unplugged rather than only if the
transport misparses. The chart test rasterizes an actual SVG in-process:
the rasterizer this replaced returns `None` on machines without a cairo
backend, and a chart path proved only against a mock would have looked
exactly as healthy as one that draws nothing.

## Layout

| File | What it owns |
|---|---|
| `src/aughor.ts` | one `/ask` turn → an `AsyncIterable` of prose and cards; artifacts out; cancel on abandon |
| `src/progress.ts` | Aughor's progress frames → Slack `task_update` cards |
| `src/artifacts.ts` | the grid → an inline table, a CSV, or both; the deep link |
| `src/chart.ts` | `/charts/svg` → PNG |
| `src/bot.ts` | mention in, answer out, exhibits after |
| `src/index.ts` | the Socket Mode entrypoint |

## Two things worth knowing before changing it

**Aughor partials are REPLACE-semantic** — every `*_delta` frame carries the
full text so far — while a posted stream **appends** each yield. `src/aughor.ts`
tracks what it has already emitted per channel and yields suffixes only. Undo
that and every answer stutters its own prefix.

**A stopped run must be cancelled, not just dropped.** Since FL-1 detached
producers from their viewers, closing the SSE connection no longer stops the
work — it only stops anyone watching it spend. The transport posts to
`/investigations/{id}/cancel` when it is abandoned mid-run.
