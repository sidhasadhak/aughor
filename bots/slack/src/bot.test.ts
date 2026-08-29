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
import { describe, expect, it, type Mock } from "vitest";
import type { Adapter } from "chat";

import type { AskOptions, TurnArtifacts } from "./aughor.js";
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

/** The exhibits ride the LAST post — the streamed answer posts first. */
function lastPost(adapter: Adapter): unknown {
  const calls = (adapter.postMessage as unknown as Mock).mock.calls;
  return calls[calls.length - 1]?.[1];
}

function askYielding(chunks: string[], artifacts?: Partial<TurnArtifacts>) {
  const seen: AskOptions[] = [];
  async function* ask(_q: string, opts: AskOptions) {
    seen.push(opts);
    for (const c of chunks) yield c;
    if (artifacts) {
      opts.onTurn?.({
        investigationId: "inv-1", question: "why?", sessionId: opts.sessionId,
        columns: [], rows: [], chartType: "auto", chartConfig: {}, ...artifacts,
      });
    }
  }
  return { ask, seen };
}

describe("buildBot — RC-2", () => {
  it("every answer carries the way back to the platform", async () => {
    const adapter = mockAughorAdapter();
    const { ask } = askYielding(["East leads."]);
    const bot = buildBot({
      ask, adapters: { slack: adapter }, state: createMockState(),
      webUrl: "https://aughor.example.com",
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    expect(adapter).toHaveEdited(
      THREAD, "msg-1",
      /East leads\.\n\n<https:\/\/aughor\.example\.com\/chat\?chat=slack%3AC1%3A1712\.001\|Open in Aughor →>/,
    );
  });

  it("no web url, no link — a wrong host is worse than none", async () => {
    const adapter = mockAughorAdapter();
    const { ask } = askYielding(["East leads."]);
    const bot = buildBot({ ask, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    expect(adapter).toHaveEdited(THREAD, "msg-1", /^East leads\.$/);
  });

  it("the turn's exhibits follow the answer as their own message — table and chart", async () => {
    const adapter = mockAughorAdapter();
    const { ask } = askYielding(["East leads."], {
      columns: ["region", "revenue"],
      rows: [["East", 12], ["West", 9]],
      chartType: "bar",
    });
    const bot = buildBot({
      ask,
      renderChart: async () => Buffer.from("PNGBYTES"),
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    const post = lastPost(adapter) as { markdown: string; files: { filename: string }[] };
    expect(post.markdown).toContain("| East | 12 |");
    expect(post.files.map((f) => f.filename)).toEqual(["chart.png"]);
  });

  it("a wide result is attached as CSV, never tabled into a wall", async () => {
    const adapter = mockAughorAdapter();
    const { ask } = askYielding(["Here."], {
      columns: ["a", "b", "c", "d", "e", "f", "g"],
      rows: [[1, 2, 3, 4, 5, 6, 7], [8, 9, 10, 11, 12, 13, 14]],
    });
    const bot = buildBot({
      ask, renderChart: async () => null,
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    const post = lastPost(adapter) as { markdown: string; files: { filename: string }[] };
    expect(post.markdown).toBe("_2 rows × 7 columns — attached as CSV._");
    expect(post.files.map((f) => f.filename)).toEqual(["why.csv"]);
  });

  it("a one-number result gets no exhibit — the prose already said it", async () => {
    const adapter = mockAughorAdapter();
    const { ask } = askYielding(["Revenue was €1.2M."], {
      columns: ["revenue"], rows: [[1200000]],
    });
    const bot = buildBot({
      ask, renderChart: async () => Buffer.from("PNGBYTES"),
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor how much?"));

    // Only the streamed answer's own placeholder post — nothing followed it.
    expect((adapter.postMessage as unknown as Mock).mock.calls).toHaveLength(1);
  });

  it("a failed chart render costs the picture, not the answer", async () => {
    const adapter = mockAughorAdapter();
    const { ask } = askYielding(["East leads."], {
      columns: ["region", "revenue"], rows: [["East", 12], ["West", 9]],
    });
    const bot = buildBot({
      ask, renderChart: async () => null,       // no honest chart, or no renderer
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    const post = lastPost(adapter) as { markdown: string; files?: unknown[] };
    expect(post.markdown).toContain("| East | 12 |");
    expect(post.files).toBeUndefined();
  });

  it("the platform's stop signal reaches the transport", async () => {
    // Without this the stop button stops the VIEW and leaves the run burning:
    // FL-1 detached the producer, so only a server-side cancel ends the spend.
    const adapter = mockAughorAdapter();
    const { ask, seen } = askYielding(["partial"]);
    const bot = buildBot({ ask, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    expect(seen).toHaveLength(1);
    expect(seen[0].signal).toBeInstanceOf(AbortSignal);
    expect(seen[0].sessionId).toBe(THREAD);
  });
});
