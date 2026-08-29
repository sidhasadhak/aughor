/**
 * The seam test: a mention drives the REAL Chat pipeline (mention detection,
 * thread resolution, post streaming) with a mock adapter and a fake ask.
 * This fails if the handler is unplugged — not merely if the transport
 * misparses — which is the built-but-not-wired failure the whole repo guards.
 */
import {
  createMockAdapter,
  createMockState,
  createTestMessage,
} from "@chat-adapter/tests";
import { describe, expect, it } from "vitest";

import type { AskOptions } from "./aughor.js";
import { buildBot, stripMention } from "./bot.js";

const THREAD = "slack:C1:1712.001";

// Mention detection matches the ADAPTER's userName (the real Slack adapter
// resolves the installed bot's name); the mock defaults to "slack-bot", so
// align it with the bot we build.
const mockAughorAdapter = () => createMockAdapter("slack", { userName: "aughor" });

function fakeAsk(chunks: string[]) {
  const calls: { question: string; opts: AskOptions }[] = [];
  async function* ask(question: string, opts: AskOptions) {
    calls.push({ question, opts });
    for (const c of chunks) yield c;
  }
  return { ask, calls };
}

describe("buildBot", () => {
  it("a mention streams the governed answer into the thread", async () => {
    const adapter = mockAughorAdapter();
    const { ask, calls } = fakeAsk(["East is flat.", " South is down 4%."]);
    const bot = buildBot({ ask, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(
      adapter,
      THREAD,
      createTestMessage("m1", "@aughor why did revenue dip?"),
    );

    // Streaming is post-then-edit: the placeholder posts, the accumulated
    // answer arrives through edits — the FINAL edit carries the whole text.
    expect(adapter).toHavePosted(THREAD);
    expect(adapter).toHaveEdited(THREAD, "msg-1", /East is flat\. South is down 4%\./);
    expect(calls).toHaveLength(1);
    expect(calls[0].question).toBe("why did revenue dip?");
    // The thread IS the conversation — follow-ups in the thread must compose.
    expect(calls[0].opts.sessionId).toBe(THREAD);
  });

  it("a bare mention gets usage, and spends nothing", async () => {
    const adapter = mockAughorAdapter();
    const { ask, calls } = fakeAsk(["never"]);
    const bot = buildBot({ ask, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m2", "@aughor"));

    expect(adapter).toHavePosted(THREAD, /Ask me a data question/);
    expect(calls).toHaveLength(0);
  });

  it("an unmentioned message is not answered — reply on address, never on overhear", async () => {
    const adapter = mockAughorAdapter();
    const { ask, calls } = fakeAsk(["never"]);
    const bot = buildBot({ ask, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(
      adapter,
      THREAD,
      createTestMessage("m3", "let's look at revenue tomorrow"),
    );

    expect(calls).toHaveLength(0);
  });
});

describe("stripMention", () => {
  it("removes plain and raw mention tokens, keeping the question", () => {
    expect(stripMention("@aughor why did revenue dip?")).toBe("why did revenue dip?");
    expect(stripMention("<@U0AUGHOR> why did revenue dip?")).toBe("why did revenue dip?");
    expect(stripMention("hey @Aughor — why?")).toBe("hey — why?");
    // The SDK normalizes a Slack mention to "@" + user id WITHOUT brackets —
    // seen live: the raw token leaked into the question and the session title.
    expect(stripMention("@U0BT4QWH0KH why did revenue dip most recently")).toBe(
      "why did revenue dip most recently",
    );
  });
});
