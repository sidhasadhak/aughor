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

The bot answers mentions with the scopes from the Chat SDK's stock manifest.
Three of the four RC-2 surfaces need more than that, and **they fail quietly
without it** — Slack's structured streaming chunks are skipped with a
debug-level log line, so a bot missing these scopes looks perfectly healthy
while showing none of it.

| Surface | Needs | Without it |
|---|---|---|
| Streamed answer, threading, follow-ups | the stock manifest | works |
| Progress cards during a deep run | Agents & AI Apps + `assistant:write` | silently absent; answer still arrives |
| Native stop button → server-side cancel | Agents & AI Apps + `assistant:write` | no stop button exists |
| Chart PNG and CSV attachments | `files:write` | the upload fails; the inline table still posts |
| Inline table, deep link | the stock manifest | works |

To turn the rest on, at [api.slack.com/apps](https://api.slack.com/apps):

1. **OAuth & Permissions → Bot Token Scopes** — add `assistant:write` and
   `files:write` to what is already there.
2. **Agents & AI Apps** — enable it. (This is the `agent_view` experience;
   Slack deprecated the older `assistant_view` and retires it in February 2027.)
3. **Event Subscriptions → Subscribe to bot events** — add `app_home_opened`,
   `app_context_changed`, `agent_session_stopped`, `agent_session_title_changed`
   alongside the existing `app_mention` and `message.*` events.
4. **Reinstall the app to the workspace.** Scope changes do not take effect
   until you do, and this is the step that is easy to skip.
5. Set `SLACK_AGENT_VIEW=1` in `.env.local` — see below for why it is a flag
   and not an assumption.

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
| `AUGHOR_API_KEY` | **required for the multi-bot supervisor.** `GET /slack-bots/runtime` is the one route that returns raw `xoxb-`/`xapp-` tokens, so it refuses to answer a deployment that authenticates nobody — set the same value on the API and here. Single-bot mode (the three `SLACK_*` vars above) does not read that route and needs no key. |
| `AUGHOR_CONNECTION_ID` | which connection to answer from; defaults to `workspace` |
| `AUGHOR_WEB_URL` | where "Open in Aughor →" points. Unset, answers simply carry no link — a wrong host is worse than none. |
| `LOG_LEVEL` | `debug` shows every incoming envelope, and the adapter's own streaming decisions ("using fallback stream — …"). The difference between "Slack never sent the event" and "it arrived and nothing matched" is invisible at `info`. |

## Running

```bash
npm install
npm run dev
```

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
