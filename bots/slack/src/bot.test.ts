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

import type { AnswerEnvelope, AskOptions, TurnArtifacts } from "./aughor.js";
import { buildBot, stripMention, withoutTables } from "./bot.js";

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
  it("an answer is the answer — no link back to the platform", async () => {
    // The user's call, 2026-09-23: "dont keep deeplink". Every answer used to end with
    // "<…|Open in Aughor →>". It reads as the same decision that took receipts off Slack
    // messages a day earlier — the message is for the people in the channel, and a trail
    // back into the platform is not what they are there for. The record still exists in
    // Aughor; the Slack message just stops advertising it.
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

// ── HB-5 · the note verb: arrivals, never asks ──────────────────────────────────

import { parseSlackThreadRef } from "./bot.js";
import type { ArrivalBody, ArrivalResult } from "./aughor.js";

function fakeArrivals(result: Partial<ArrivalResult> = {}) {
  const posted: ArrivalBody[] = [];
  const postArrival = async (body: ArrivalBody): Promise<ArrivalResult> => {
    posted.push(body);
    return { ok: true, status: 200, detail: "staged for human review", ...result };
  };
  return { postArrival, posted };
}

describe("parseSlackThreadRef", () => {
  it("reads channel and root ts off the adapter's colon-joined id", () => {
    expect(parseSlackThreadRef("slack:C1:1712.001")).toEqual({ channel: "C1", ts: "1712.001" });
    expect(parseSlackThreadRef("C1:1712.001")).toEqual({ channel: "C1", ts: "1712.001" });
  });
  it("refuses an id with no ts tail rather than guessing", () => {
    expect(parseSlackThreadRef("slack:C1")).toBeNull();
    expect(parseSlackThreadRef("")).toBeNull();
  });
});

describe("the note verb", () => {
  it("files the sentence through the arrivals door and never calls ask", async () => {
    const adapter = mockAughorAdapter();
    const { ask, calls } = fakeAsk(["never"]);
    const { postArrival, posted } = fakeArrivals();
    const bot = buildBot({ ask, postArrival, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(
      adapter,
      THREAD,
      createTestMessage("m9", "@aughor note: carrier X was on strike last week"),
    );

    expect(calls).toHaveLength(0);                      // an arrival is not an ask
    expect(posted).toHaveLength(1);
    expect(posted[0].channel).toBe("C1");
    expect(posted[0].threadTs).toBe("1712.001");
    expect(posted[0].text).toBe("carrier X was on strike last week");
    expect(adapter).toHavePosted(THREAD);               // the door's sentence, repeated
  });

  it("repeats the door's refusal honestly on an unfiled thread", async () => {
    const adapter = mockAughorAdapter();
    const { ask, calls } = fakeAsk(["never"]);
    const { postArrival } = fakeArrivals({ ok: false, status: 404,
      detail: "thread C1:1712.001 is not filed on any object — nothing to note" });
    const bot = buildBot({ ask, postArrival, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(
      adapter, THREAD, createTestMessage("m10", "@aughor note: this thread is unfiled"));

    expect(calls).toHaveLength(0);
    expect(adapter).toHavePosted(THREAD);
  });

  it("without the verb, a question still asks — the arrival path never hijacks", async () => {
    const adapter = mockAughorAdapter();
    const { ask, calls } = fakeAsk(["East is flat."]);
    const { posted, postArrival } = fakeArrivals();
    const bot = buildBot({ ask, postArrival, adapters: { slack: adapter }, state: createMockState() });

    await bot.handleIncomingMessage(
      adapter, THREAD, createTestMessage("m11", "@aughor note that revenue dipped?"));

    // The COLON is the verb: "note that…" is prose and asks; only "note: …" files.
    expect(posted).toHaveLength(0);
    expect(calls).toHaveLength(1);
  });
});

describe("withoutTables — a table the model typed never reaches the thread (CP-4)", () => {
  async function* chunks(...parts: (string | { kind: string })[]) {
    for (const p of parts) yield p as never;
  }
  const text = async (parts: (string | { kind: string })[]) => {
    const out: string[] = [];
    for await (const c of withoutTables(chunks(...parts))) if (typeof c === "string") out.push(c);
    return out.join("");
  };

  it("drops a GFM table split across arbitrary chunks and keeps the prose around it", async () => {
    const got = await text(["Top regions:\n\n| # | Reg", "ion |\n|---|---|\n| 1 | East |\n| 2 | We", "st |\n\nEast leads."]);
    expect(got).toBe("Top regions:\n\n\nEast leads.");
  });

  it("releases a pipe run that has no delimiter under it — prose, not a table", async () => {
    expect(await text(["We compared revenue | margin.\nThen a | b\nand stopped."]))
      .toBe("We compared revenue | margin.\nThen a | b\nand stopped.");
  });

  it("judges a table with no trailing newline with the run it belongs to", async () => {
    expect(await text(["Here:\n| a | b |\n|---|---|\n| 1 | 2 |"])).toBe("Here:\n");
  });

  it("releases the last unterminated line and passes non-text chunks through", async () => {
    const out: unknown[] = [];
    for await (const c of withoutTables(chunks("East is", { kind: "card" }, " flat."))) out.push(c);
    expect(out).toEqual(["East is", { kind: "card" }, " flat."]);
  });
});

describe("buildBot — the grid posts once, from the envelope (CP-4)", () => {
  const GRID = {
    columns: ["region", "revenue"],
    rows: [["East", 12], ["West", 9]] as unknown[][],
    chartType: "bar",
  };
  /** What a model writes when it tabulates in prose — different headers, same rows. */
  const TABULATED =
    "Top regions:\n\n| # | Region | Revenue |\n|---|--------|---------|\n| 1 | East | 12 |\n| 2 | West | 9 |\n";

  const editedText = (adapter: Adapter): string =>
    (adapter.editMessage as unknown as Mock).mock.calls.map((c) => JSON.stringify(c[2])).join("\n");

  it("the model's own table never reaches the thread; the grid posts once, as the exhibit", async () => {
    // Measured 2026-09-23: a real answer carried the same five rows twice — the model's
    // table in the prose, then the transport's grid. The prose table is held back as it
    // streams; the grid is the one field that renders it.
    const adapter = mockAughorAdapter();
    const { ask } = askYielding([TABULATED], GRID);
    const bot = buildBot({
      ask, renderChart: async () => Buffer.from("PNGBYTES"),
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    expect(adapter).toHaveEdited(THREAD, "msg-1", /Top regions:/);
    expect(editedText(adapter)).not.toContain("| 1 | East |");
    const post = lastPost(adapter) as { markdown: string; files: { filename: string }[] };
    expect(post.markdown).toContain("| East | 12 |");
    expect(post.markdown.match(/East/g)).toHaveLength(1);
    expect(post.files.map((f) => f.filename)).toEqual(["chart.png"]);
  });

  it("selects the envelope's grid, chart decision and top two caveats — never its provenance", async () => {
    const adapter = mockAughorAdapter();
    const rendered: Record<string, unknown>[] = [];
    const envelope: AnswerEnvelope = {
      version: 1, question: "why?", headline: "East leads.", body: "",
      grid: { columns: ["region", "revenue"], rows: [["East", 12], ["West", 9]] },
      chart: { chart_type: "bar", chart_config: { exhibit: { kind: "ranked" } } },
      caveats: ["returns counted at request", "March is still settling", "a third caveat"],
      follow_ups: ["Which region next?"],
      provenance: { guard_receipts: [{ guard: "numeric grounding", action: "rewrote the answer" }] },
      error: "", lifted_tables: 0,
    };
    // The frame-level artifacts disagree with the envelope on purpose: the envelope wins.
    const { ask } = askYielding(["East leads."], { columns: ["x"], rows: [[1]], chartType: "line", envelope });
    const bot = buildBot({
      ask, renderChart: async (req) => { rendered.push(req as unknown as Record<string, unknown>); return Buffer.from("PNG"); },
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    const post = lastPost(adapter) as { markdown: string; files: { filename: string }[] };
    expect(post.markdown).toContain("| East | 12 |");
    expect(post.markdown).toContain("⚠️ returns counted at request");
    expect(post.markdown).toContain("⚠️ March is still settling");
    expect(post.markdown).not.toContain("a third caveat");
    expect(post.markdown).not.toContain("numeric grounding");
    expect(post.markdown).not.toContain("Which region next?");
    expect(rendered).toHaveLength(1);
    expect(rendered[0].chart_type).toBe("bar");
    expect(rendered[0].chart_config).toEqual({ exhibit: { kind: "ranked" } });
    expect(rendered[0].columns).toEqual(["region", "revenue"]);
  });

  it("keeps the exhibit table when the answer is prose", async () => {
    const adapter = mockAughorAdapter();
    const { ask } = askYielding(["East leads, and it is not close."], GRID);
    const bot = buildBot({
      ask, renderChart: async () => null,
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    expect((lastPost(adapter) as { markdown: string }).markdown).toContain("| East | 12 |");
  });

  it("a one-number envelope with a caveat posts the caveat and no table", async () => {
    const adapter = mockAughorAdapter();
    const envelope: AnswerEnvelope = {
      version: 1, question: "q", headline: "Revenue was $1.2M.", body: "",
      grid: { columns: ["revenue"], rows: [[1.2e6]] }, chart: { chart_type: "auto", chart_config: {} },
      caveats: ["excludes refunds"], follow_ups: [], provenance: {}, error: "", lifted_tables: 0,
    };
    const { ask } = askYielding(["Revenue was $1.2M."], { envelope });
    const bot = buildBot({
      ask, renderChart: async () => Buffer.from("PNG"),
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor q"));

    const post = lastPost(adapter) as { markdown: string; files?: unknown[] };
    expect(post.markdown).toBe("⚠️ excludes refunds");
    expect(post.files).toBeUndefined();
  });

  it("keeps a PREVIEW for a long grid — its caption is the only thing naming the rest", async () => {
    // A long grid renders as first-rows + CSV, and "Showing N of M rows" is what tells the
    // reader more exists. The model's own table is an excerpt too, so dropping the caption
    // would hide the remainder rather than de-duplicate it.
    const adapter = mockAughorAdapter();
    const rows = Array.from({ length: 60 }, (_, i) => [`r${i}`, i]) as unknown[][];
    const { ask } = askYielding([TABULATED], { columns: ["region", "revenue"], rows });
    const bot = buildBot({
      ask, renderChart: async () => null,
      adapters: { slack: adapter }, state: createMockState(),
    });

    await bot.handleIncomingMessage(adapter, THREAD, createTestMessage("m1", "@aughor why?"));

    const post = lastPost(adapter) as { markdown: string; files: { filename: string }[] };
    expect(post.markdown).toContain("of 60 rows");
    expect(post.files.map((f) => f.filename)).toEqual(["why.csv"]);
  });
});
