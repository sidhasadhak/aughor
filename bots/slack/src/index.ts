/**
 * RC-1 entrypoint — a long-lived Socket Mode process for a laptop deployment.
 *
 * Socket Mode connects OUT to Slack over WebSocket, so no public URL, tunnel,
 * or webhook endpoint exists; the adapter's `initialize()` opens the socket
 * when `mode: "socket"` is set. Run with `npm run dev` (loads `.env.local`).
 */
import { createSlackAdapter } from "@chat-adapter/slack";
import { createMemoryState } from "@chat-adapter/state-memory";

import { createAskStream } from "./aughor.js";
import { buildBot } from "./bot.js";

for (const name of ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN"]) {
  if (!process.env[name]) {
    console.error(`Missing ${name} — copy .env.local.example to .env.local and fill it in.`);
    process.exit(1);
  }
}

const bot = buildBot({
  ask: createAskStream(),
  adapters: {
    slack: createSlackAdapter({
      mode: "socket",
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
  `· connection "${process.env.AUGHOR_CONNECTION_ID ?? "workspace"}"`,
);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    void bot.shutdown().finally(() => process.exit(0));
  });
}
