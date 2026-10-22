// @vitest-environment jsdom
/**
 * One feedback control per answer, whatever is open. 2026-10-22: a finished quick answer drew
 * two thumbs pairs — the panel's under the answer and a second inside "Methodology & details"
 * — and both posted the same verdict for the same receipt. The panel is rendered whole over a
 * finished turn here, the details opened, and the pairs counted: the duplicate lived ACROSS
 * two components, so a test of either alone could not have seen it.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const MESSAGES = [
  { id: "u1", role: "user", metadata: { mode: "ask" },
    parts: [{ type: "text", text: "Do Event and Platform really join on these keys?" }] },
  { id: "a1", role: "assistant", parts: [
    { type: "text", text: "Yes. Event and Platform join cleanly on these keys.",
      providerMetadata: { aughor: { channel: "headline" } } },
    { type: "data-sql", data: { sql: "SELECT COUNT(*) AS att_rows FROM event_attendance" } },
    { type: "data-columns", data: { columns: ["att_rows"] } },
    { type: "data-rows", data: { rows: [[1642]] } },
    { type: "data-done", data: { has_receipt: true, inv_id: "inv-1" } },
  ] },
];

vi.mock("@/lib/useAughorChat", () => ({
  useAughorChat: () => ({
    messages: MESSAGES, sendMessage: vi.fn(async () => undefined), setMessages: vi.fn(),
    regenerate: vi.fn(), stop: vi.fn(), status: "ready", error: undefined, clearError: vi.fn(),
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

beforeEach(() => {
  // never the live API: the panel's prewarm and starters read through fetch
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ suggestions: [], starters: [] }), { status: 200 })));
  // the result table's grid reads the viewport; jsdom has no matchMedia
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false, media: q, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  }));
});
afterEach(() => vi.unstubAllGlobals());

const pairs = () => screen.queryAllByLabelText("Helpful").length;
const glyphs = (c: HTMLElement) => (c.textContent ?? "").split("👍").length - 1;

describe("a finished quick answer", () => {
  it("asks for feedback once — and still once with its details open", async () => {
    const { container } = render(<ChatPanel connectionId="c1" />);
    await act(async () => {});
    expect(pairs()).toBe(1);
    expect(glyphs(container)).toBe(1);

    fireEvent.click(screen.getByText("Methodology & details"));
    expect(screen.getAllByText("Validate").length).toBeGreaterThan(0);   // the query tools stay in the details
    expect(pairs()).toBe(1);
    expect(glyphs(container)).toBe(1);
  });
});
