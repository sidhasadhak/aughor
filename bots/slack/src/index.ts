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

import { createArrivalPoster, createAskStream, createFactChecker, createVerdictPoster } from "./aughor.js";
import { buildBot } from "./bot.js";
import { createChartRenderer } from "./chart.js";
import { hostname } from "node:os";

import { createHeartbeat, createRegistry, type BotRecord } from "./registry.js";
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
    // HB-5 — the note verb's transport: "@bot note: …" files the sentence on the
    // object this thread is about, through the arrivals door's customs.
    postArrival: createArrivalPoster({
      AUGHOR_API_URL: apiUrl,
      AUGHOR_API_KEY: process.env.AUGHOR_API_KEY,
    }),
    // Idea 7 — the check verb's transport: "@bot check: <memo>" checks every number in
    // the memo against this bot's connection, through the fact-check door.
    factCheck: createFactChecker({
      AUGHOR_API_URL: apiUrl,
      AUGHOR_API_KEY: process.env.AUGHOR_API_KEY,
      AUGHOR_CONNECTION_ID: record.connection_id || process.env.AUGHOR_CONNECTION_ID,
    }),
    // TJ-4 — a ✅ / ❌ on an answer is a verdict on its turn, through the verdict door.
    postVerdict: createVerdictPoster({
      AUGHOR_API_URL: apiUrl,
      AUGHOR_API_KEY: process.env.AUGHOR_API_KEY,
      AUGHOR_CONNECTION_ID: record.connection_id || process.env.AUGHOR_CONNECTION_ID,
    }),
    // AO-7b — the message→turn map outlives a restart, so a ✅ tomorrow still lands.
    // One file per bot, beside .env.local; "" would keep it in memory.
    turnMapFile: process.env.AUGHOR_TURN_MAP_FILE
      ?? `.aughor-turns.${record.id || "env"}.json`,
    // AO-6 — rehearse comes from the RECORD, the same row the card's checkbox writes:
    // a mention is answered in the asker's DM first and reaches the channel on their ✅.
    rehearse: record.rehearse ?? false,
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
    // The env path keeps its own switches: there is no record to read them from.
    agent_view: process.env.SLACK_AGENT_VIEW === "1",
    rehearse: process.env.SLACK_REHEARSE === "1",
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

// AO-2a — after every reconcile, tell Aughor what is listening. The id names THIS
// process; the API keeps the last beat and the bot card reads liveness from it.
const postHeartbeat = createHeartbeat();
const supervisorId = `${hostname()}:${process.pid}:${new Date().toISOString()}`;
let heartbeatLanded: boolean | null = null;
async function beat(failed: { id: string; error: string }[]): Promise<void> {
  const ok = await postHeartbeat({
    supervisor_id: supervisorId, running: supervisor.runningIds(), failed,
    reconcile_ms: RECONCILE_MS,
  });
  // Say it on a CHANGE of state only — a heartbeat that fails every 30 s would otherwise
  // bury the bot's own log, and the API's card already says "not listening".
  if (ok !== heartbeatLanded) {
    console[ok ? "log" : "warn"](ok
      ? "heartbeat: Aughor knows this supervisor is listening"
      : "heartbeat: Aughor could not be told this supervisor is listening (the bot card "
        + "will read 'not listening' until it can) — check AUGHOR_API_URL / AUGHOR_RUNTIME_KEY");
    heartbeatLanded = ok;
  }
}

// AO-2b — under the API's host this process must outlive an empty registry: the sockets
// are what keep a standalone run alive, and on a FRESH install there are none yet, so an
// unref'd timer let the child exit 0 after its first heartbeat and the host restarted it
// every five seconds until its hourly cap (measured 2026-10-03 on a scratch API: seven
// restarts in a minute). Managed, the reconcile timer holds the process open and the first
// bot a person creates is picked up on the next tick.
const managedByApi = process.env.AUGHOR_MANAGED_BY_API === "1";

const first = await supervisor.reconcile();
if (first.running === 0) {
  console.error(managedByApi
    ? "No bots to run yet — waiting; the first bot created in Aughor (Integrations → Slack) " +
      `is picked up within ${Math.round(RECONCILE_MS / 1000)}s.`
    : "No bots to run. Create one in Aughor (Slack bots → New), or fill in " +
      ".env.local with SLACK_BOT_TOKEN / SLACK_APP_TOKEN / SLACK_SIGNING_SECRET.",
  );
} else {
  console.log(
    `aughor-slack-bot: ${first.running} bot(s) connected (socket mode) → ${apiUrl}`,
  );
}
for (const f of first.failed) console.error(`  bot ${f.id} did not start: ${f.error}`);
await beat(first.failed);

const timer = setInterval(() => {
  void supervisor.reconcile().then(async (r) => {
    if (r.started.length || r.stopped.length || r.restarted.length) {
      console.log(`reconciled: +${r.started.length} -${r.stopped.length} ` +
                  `~${r.restarted.length} (${r.running} running)`);
    }
    await beat(r.failed);
  });
}, RECONCILE_MS);
// Standalone, reconciling must never be the reason the process stays alive; the sockets
// are, and a person watching the terminal sees "No bots to run" and an exit. Managed, the
// API's host IS the watcher, and an exit here is a restart loop (see above).
if (!managedByApi) timer.unref?.();

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    clearInterval(timer);
    void supervisor.shutdown().finally(() => process.exit(0));
  });
}
