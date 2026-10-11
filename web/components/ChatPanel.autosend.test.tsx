// @vitest-environment jsdom
/**
 * A question injected from outside — the Briefing's "Open in Ask", or any button that hands the chat a question —
 * is sent into the conversation on screen, and shown there.
 *
 * 2026-10-11: "Open in Ask" landed on an empty chat while its run went on. The panel minted a second session on
 * mount, so the auto-send — bound to the render that set its timer — wrote the question into the first session
 * (the server kept it, with the finished report) while the screen showed the second, empty one.
 */
import { act, render, screen } from "@testing-library/react";
import { useReducer } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sent: { session: string; text: string }[] = [];
const stores = new Map<string, unknown[]>();
const rendered = new Set<string>();     // every session the panel has drawn

vi.mock("@/lib/useAughorChat", () => ({
  // The real hook builds one Chat per session id, and that Chat's sendMessage writes into ITS conversation —
  // so a send bound to an earlier session lands where the screen no longer looks. This double keeps that binding.
  useAughorChat: ({ sessionId }: { sessionId: string }) => {
    const [, bump] = useReducer((n: number) => n + 1, 0);
    rendered.add(sessionId);
    return {
      messages: stores.get(sessionId) ?? [],
      sendMessage: (m: { text: string }) => {
        sent.push({ session: sessionId, text: m.text });
        stores.set(sessionId, [...(stores.get(sessionId) ?? []),
          { id: `u${sent.length}`, role: "user", parts: [{ type: "text", text: m.text }] }]);
        bump();
        return Promise.resolve();
      },
      setMessages: vi.fn(), regenerate: vi.fn(), stop: vi.fn(), status: "ready", error: undefined, clearError: vi.fn(),
    };
  },
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getConnections: vi.fn(async () => []),
  getSystemFlags: vi.fn(async () => ({})),
  listUserAgents: vi.fn(async () => []),
  recordOverviewDrill: vi.fn(),
  cancelInvestigation: vi.fn(async () => undefined),
  cancelActiveDeepRun: vi.fn(),
}));

import { ChatPanel } from "./ChatPanel";

// the Briefing hands over its claim as the question (its own prefix aside)
const QUESTION = "Web Session Conversion Rate has fallen from 100% to 31% (-69%) over the period.";

beforeEach(() => {
  sent.length = 0;
  stores.clear();
  rendered.clear();
  vi.useFakeTimers();
  // never the live API: the panel's prewarm and starters read through fetch
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ suggestions: [], starters: [] }), { status: 200 })));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(300); });

describe("a question injected from outside", () => {
  it("is sent once, into the conversation on screen, and shown there", async () => {
    render(<ChatPanel connectionId="c1" initialQuestion={QUESTION} />);
    await settle();
    expect(sent.map(s => s.text)).toEqual([QUESTION]);
    expect(screen.getAllByText(QUESTION).length).toBeGreaterThan(0);
  });

  it("leaves the panel on the conversation it mounted with", async () => {
    render(<ChatPanel connectionId="c1" initialQuestion={QUESTION} />);
    await settle();
    expect(rendered.size).toBe(1);
    expect(sent[0].session).toBe([...rendered][0]);
  });

  it("goes to the new connection's conversation when the reader moves before it is sent", async () => {
    const { rerender } = render(<ChatPanel connectionId="c1" initialQuestion={QUESTION} />);
    rerender(<ChatPanel connectionId="c2" initialQuestion={QUESTION} />);
    await settle();
    expect(sent.map(s => s.text)).toEqual([QUESTION]);
    expect(screen.getAllByText(QUESTION).length).toBeGreaterThan(0);
  });

  it("waits for its connection, and is then sent into the conversation on screen", async () => {
    const { rerender } = render(<ChatPanel connectionId="" initialQuestion={QUESTION} />);
    await settle();
    expect(sent).toEqual([]);                                    // nothing asked of no connection
    rerender(<ChatPanel connectionId="c1" initialQuestion={QUESTION} />);
    await settle();
    expect(sent.map(s => s.text)).toEqual([QUESTION]);
    expect(screen.getAllByText(QUESTION).length).toBeGreaterThan(0);
  });

  it("stays its conversation's until the reader moves to another connection, which starts a new one", async () => {
    const { rerender } = render(<ChatPanel connectionId="c1" initialQuestion={QUESTION} />);
    await settle();
    expect(screen.getAllByText(QUESTION).length).toBeGreaterThan(0);
    rerender(<ChatPanel connectionId="c2" initialQuestion={QUESTION} />);
    await settle();
    expect(screen.queryAllByText(QUESTION)).toEqual([]);         // a new connection, a new conversation
    expect(sent).toHaveLength(1);                                // and the question is not asked again
  });
});
