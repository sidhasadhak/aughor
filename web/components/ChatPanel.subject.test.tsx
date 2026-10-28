// @vitest-environment jsdom
/**
 * Arc FA-2 — the Data Canvas carries what a reader chose on a dashboard. The subject
 * stands above the input ("Asking about 12 orders · from Late dispatch"), a plain question sends it as `focus` through the
 * one door that reads one, and it can be taken off. A subject chosen on another connection is not this conversation's.
 * The chat transport is a double: no network.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { nounOf, setAskSubject, type AskSubject } from "@/lib/askSubject";

const sent: { text: string; body: Record<string, unknown> }[] = [];

vi.mock("@/lib/useAughorChat", () => ({
  useAughorChat: () => ({
    messages: [],
    sendMessage: (m: { text: string }, o: { body: Record<string, unknown> }) => { sent.push({ text: m.text, body: o.body }); return Promise.resolve(); },
    setMessages: vi.fn(), regenerate: vi.fn(), stop: vi.fn(), status: "ready", error: undefined, clearError: vi.fn(),
  }),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getConnections: vi.fn(async () => []),
  getSystemFlags: vi.fn(async () => ({})),
  listUserAgents: vi.fn(async () => []),
  recordOverviewDrill: vi.fn(),
  cancelActiveDeepRun: vi.fn(),
}));

import { ChatPanel } from "./ChatPanel";

const TICKED: AskSubject = { kind: "objects", connectionId: "thelook", noun: nounOf("Order"), label: "Late dispatch",
  refs: Array.from({ length: 12 }, (_, i) => `order:${48200 + i}`) };

beforeEach(() => {
  sent.length = 0;
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ suggestions: [], starters: [] }), { status: 200 })));
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => setAskSubject(null));
});

const ask = (q: string) => {
  const box = screen.getByPlaceholderText("Ask anything about your data…");
  fireEvent.change(box, { target: { value: q } });
  fireEvent.keyDown(box, { key: "Enter" });
};

describe("a question about what a reader chose", () => {
  it("stands above the input and is sent as the turn's focus through the ask door", async () => {
    act(() => setAskSubject(TICKED));
    render(<ChatPanel connectionId="thelook" />);
    await act(async () => {});
    expect(screen.getByTestId("chat-subject")).toHaveTextContent("Asking about 12 orders · from Late dispatch");
    ask("What do these have in common?");
    expect(sent).toHaveLength(1);
    expect(sent[0].body).toMatchObject({ mode: "auto", depth: "deep", focus: { kind: "objects", objects: TICKED.kind === "objects" ? TICKED.refs : [], label: "Late dispatch" } });
  });

  it("is taken off with its ×, and the next question is asked as before", async () => {
    act(() => setAskSubject(TICKED));
    render(<ChatPanel connectionId="thelook" />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId("chat-subject-drop"));
    expect(screen.queryByTestId("chat-subject")).toBeNull();
    ask("And overall?");
    expect(sent[0].body).not.toHaveProperty("focus");
  });

  it("is not this conversation's when it was chosen on another connection", async () => {
    act(() => setAskSubject({ ...TICKED, connectionId: "olist" }));
    render(<ChatPanel connectionId="thelook" />);
    await act(async () => {});
    expect(screen.queryByTestId("chat-subject")).toBeNull();
    ask("What do these have in common?");
    expect(sent[0].body).not.toHaveProperty("focus");
  });
});
