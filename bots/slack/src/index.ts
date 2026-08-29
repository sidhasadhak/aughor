/**
 * RC-1/RC-2 entrypoint — a long-lived Socket Mode process for a laptop deployment.
 *
 * Socket Mode connects OUT to Slack over WebSocket, so no public URL, tunnel,
 * or webhook endpoint exists; the adapter's `initialize()` opens the socket
 * when `mode: "socket"` is set. Run with `npm run dev` (loads `.env.local`).
 */
import { createSlackAdapter } from "@chat-adapter/slack";
import { createMemoryState } from "@chat-adapter/state-memory";

import { createAskStream } from "./aughor.js";
import { buildBot } from "./bot.js";
import { createChartRenderer } from "./chart.js";

for (const name of ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN"]) {
  if (!process.env[name]) {
    console.error(`Missing ${name} — copy .env.local.example to .env.local and fill it in.`);
    process.exit(1);
  }
}

const bot = buildBot({
  ask: createAskStream(),
  renderChart: createChartRenderer(),
  // Where "Open in Aughor →" points. Absent, answers simply carry no link —
  // a wrong host is worse than none, so this is never guessed.
  webUrl: process.env.AUGHOR_WEB_URL,
  adapters: {
    slack: createSlackAdapter({
      mode: "socket",
      // Slack's Agent messaging: session lifecycle, and the native stop button
      // whose abort reaches `thread.signal`. It requires a manifest in
      // `agent_view` mode, so it is opt-in rather than assumed — turning it on
      // against an assistant_view app makes `stopStream` send a parameter that
      // app cannot accept, which would cost the final message of every answer.
      // Flip it in the same pass that adds the agent feature (see README).
      agentView: process.env.SLACK_AGENT_VIEW === "1",
      appToken: process.env.SLACK_APP_TOKEN!,
      botToken: process.env.SLACK_BOT_TOKEN!,
      signingSecret: process.env.SLACK_SIGNING_SECRET!,
    }),
  },
  state: createMemoryState(),
});

await bot.initialize();
console.log(
  `aughor-slack-bot connected (socket mode) → ${process.env.AUGHOR_API_URL ?? "http://127.0.0.1:8000"} ` +
  `· connection "${process.env.AUGHOR_CONNECTION_ID ?? "workspace"}"` +
  `${process.env.AUGHOR_WEB_URL ? ` · links → ${process.env.AUGHOR_WEB_URL}` : " · no AUGHOR_WEB_URL, answers carry no link"}`,
);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    void bot.shutdown().finally(() => process.exit(0));
  });
}
