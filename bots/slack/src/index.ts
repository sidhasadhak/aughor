/**
 * RC-5 entrypoint — one long-lived process serving N bots.
 *
 * Socket Mode connects OUT to Slack over WebSocket, so no public URL, tunnel, or
 * webhook endpoint exists; the adapter's `initialize()` opens the socket when
 * `mode: "socket"` is set. Run with `npm run dev` (loads `.env.local`).
 *
 * REGISTRY FIRST, ENV FALLBACK. Where Aughor holds bot records this process runs all of
 * them, reconciling on a timer so a bot created in the UI comes up without a restart.
 * Where it holds none and `.env.local` has credentials, it runs that single bot exactly
 * as RC-1 did — so an existing laptop deployment keeps working through the change
 * instead of going dark until someone creates a record.
 *
 * RC-2's per-bot wiring (chart renderer, deep link, agent view) lives inside `makeBot`
 * rather than at module scope. That is the merge of the two waves, and it is the better
 * shape: `agent_view` in particular now comes from the RECORD, so two bots in one
 * workspace can differ on it — which they must, because it has to match each app's own
 * manifest, and Aughor writes the manifest and the record in the same act.
 */
import { createSlackAdapter } from "@chat-adapter/slack";
import { createMemoryState } from "@chat-adapter/state-memory";

import { createAskStream } from "./aughor.js";
import { buildBot } from "./bot.js";
import { createChartRenderer } from "./chart.js";
import { createRegistry, type BotRecord } from "./registry.js";
import { createSupervisor } from "./supervisor.js";

/** How often to ask Aughor what should be running. */
const RECONCILE_MS = Number(process.env.AUGHOR_RECONCILE_MS ?? 30_000);

const apiUrl = process.env.AUGHOR_API_URL ?? "http://127.0.0.1:8000";

/** Built once and shared: the renderer is stateless and holds no per-bot config. */
const renderChart = createChartRenderer();

/** One Chat instance for one record — the per-bot wiring lives here, not in the supervisor. */
async function makeBot(record: BotRecord) {
  const bot = buildBot({
    // Each bot gets its OWN synthetic env: same transport, different agent and
    // warehouse. That is the entire difference between two bots.
    ask: createAskStream({
      AUGHOR_API_URL: apiUrl,
      AUGHOR_API_KEY: process.env.AUGHOR_API_KEY,
      AUGHOR_CONNECTION_ID: record.connection_id || process.env.AUGHOR_CONNECTION_ID,
      AUGHOR_AGENT_ID: record.agent_id,
    }),
    renderChart,
    // Where "Open in Aughor →" points. Absent, answers simply carry no link —
    // a wrong host is worse than none, so this is never guessed.
    webUrl: process.env.AUGHOR_WEB_URL,
    adapters: {
      slack: createSlackAdapter({
        mode: "socket",
        // Slack's Agent messaging: session lifecycle, and the native stop button whose
        // abort reaches `thread.signal`. It requires the app's manifest to be in
        // `agent_view` mode, so it comes from the RECORD — Aughor renders the manifest
        // and stores the flag in one act, which is the only way the two cannot disagree.
        // Turning it on against an assistant_view app makes `stopStream` send a
        // parameter that app cannot accept, costing the final message of every answer.
        agentView: record.agent_view,
        appToken: record.app_token,
        botToken: record.bot_token,
        signingSecret: record.signing_secret,
      }),
    },
    state: createMemoryState(),
  });
  await bot.initialize();
  return bot;
}

/** The single bot described by `.env.local`, expressed as one registry record. */
function envBot(): BotRecord[] {
  const bot_token = process.env.SLACK_BOT_TOKEN ?? "";
  const app_token = process.env.SLACK_APP_TOKEN ?? "";
  if (!bot_token || !app_token) return [];
  return [{
    id: "env", name: "aughor (.env.local)", enabled: true,
    agent_id: process.env.AUGHOR_AGENT_ID ?? "",
    connection_id: process.env.AUGHOR_CONNECTION_ID ?? "",
    bot_token, app_token,
    signing_secret: process.env.SLACK_SIGNING_SECRET ?? "",
    // The env path keeps its own switch: there is no record to read it from.
    agent_view: process.env.SLACK_AGENT_VIEW === "1",
  }];
}

const readRegistry = createRegistry();

const supervisor = createSupervisor({
  makeBot,
  log: (m) => console.log(m),
  fetchBots: async () => {
    try {
      const bots = await readRegistry();
      if (bots.length) return bots;
    } catch (err) {
      // A registry that cannot be read is not the same as a registry with no bots. Say
      // so, then fall back — silently serving the env bot would hide a broken API.
      console.warn(`registry read failed (${String(err)}); falling back to .env.local`);
    }
    return envBot();
  },
});

const first = await supervisor.reconcile();
if (first.running === 0) {
  console.error(
    "No bots to run. Create one in Aughor (Slack bots → New), or fill in " +
    ".env.local with SLACK_BOT_TOKEN / SLACK_APP_TOKEN / SLACK_SIGNING_SECRET.",
  );
} else {
  console.log(
    `aughor-slack-bot: ${first.running} bot(s) connected (socket mode) → ${apiUrl}` +
    `${process.env.AUGHOR_WEB_URL ? ` · links → ${process.env.AUGHOR_WEB_URL}`
                                  : " · no AUGHOR_WEB_URL, answers carry no link"}`,
  );
}
for (const f of first.failed) console.error(`  bot ${f.id} did not start: ${f.error}`);

const timer = setInterval(() => {
  void supervisor.reconcile().then((r) => {
    if (r.started.length || r.stopped.length || r.restarted.length) {
      console.log(`reconciled: +${r.started.length} -${r.stopped.length} ` +
                  `~${r.restarted.length} (${r.running} running)`);
    }
  });
}, RECONCILE_MS);
// Reconciling must never be the reason the process stays alive; the sockets are.
timer.unref?.();

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    clearInterval(timer);
    void supervisor.shutdown().finally(() => process.exit(0));
  });
}
