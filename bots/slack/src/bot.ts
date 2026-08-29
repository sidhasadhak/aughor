/**
 * The bot half of RC-1: mention in, streamed governed answer out.
 *
 * Built as a factory so the tests drive the REAL Chat pipeline (mention
 * detection, threading, post streaming) with a mock adapter and a fake ask —
 * the seam that fails if the handler is unplugged, not just if the transport
 * misparses. The Python API stays the only brain; nothing here retries,
 * rephrases, or interprets.
 */
import { Chat, type Adapter, type StateAdapter } from "chat";

import type { AskStream } from "./aughor.js";

export const BOT_USERNAME = "aughor";

const USAGE =
  "Ask me a data question — e.g. “@aughor why did revenue dip last month?” " +
  "I answer from the connected warehouse, with a Trust Receipt behind every number.";

/** The question, with the bot's own mention tokens stripped off. */
export function stripMention(text: string, userName: string = BOT_USERNAME): string {
  return text
    .replace(new RegExp(`<@[A-Z0-9]+>`, "g"), " ") // Slack raw mention tokens
    .replace(new RegExp(`@${userName}\\b`, "gi"), " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildBot({
  ask,
  adapters,
  state,
}: {
  ask: AskStream;
  adapters: Record<string, Adapter>;
  state: StateAdapter;
}): Chat {
  const bot = new Chat({
    userName: BOT_USERNAME,
    adapters,
    state,
    logger: "info",
  });

  bot.onNewMention(async (thread, message) => {
    const question = stripMention(message.text ?? "");
    if (!question) {
      await thread.post(USAGE);
      return;
    }
    // The thread IS the conversation: its id rides as session_id, so follow-up
    // mentions in the same thread compose on the same Aughor conversation.
    await thread.post(ask(question, { sessionId: thread.id }));
  });

  return bot;
}
