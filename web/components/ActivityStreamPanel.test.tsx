// @vitest-environment jsdom
/**
 * The live events at the foot of Agent Ops' Overview hide the routine guardrail checks until asked for: a PII check
 * that let its call through runs on every model call and on the automation engine's per-minute check, and on theLook
 * (2026-10-13) it was 1,652 of the newest 2,000 events. A check that BLOCKED is never hidden, and the hidden ones are
 * counted where the filters are, one click from showing.
 *
 * The client is mocked: an unmocked call would reach the live API from jsdom.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionEvent } from "@/lib/api";

const reads: Array<Record<string, unknown>> = [];
let events: SessionEvent[] = [];
let refuse: string | null = null;
vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getActivityEvents: (p: Record<string, unknown>) => {
    reads.push(p);
    if (refuse) return Promise.reject(new Error(refuse));
    return Promise.resolve({ measured: true, events, kinds: { guardrail: 3, llm_call: 1 }, window: null });
  },
}));

class _NoStream { onmessage: unknown = null; onerror: unknown = null; onopen: unknown = null; readyState = 0; close() {} }
(globalThis as unknown as { EventSource: unknown }).EventSource = _NoStream;

const { ActivityStreamPanel, isRoutineCheck } = await import("@/components/ActivityStreamPanel");

/** An event as the session log serves it — only the fields these tests read. */
const ev = (seq: number, kind: string, over: Partial<SessionEvent> = {}): SessionEvent => ({
  seq, at: "2026-10-13T20:53:43Z", trace_id: `t${seq}`, kind, name: null, ok: true, payload: null, ...over,
}) as SessionEvent;

const routine = (seq: number) => ev(seq, "guardrail", { name: "pii", payload: { guardrail: "pii", blocked: false, detail: "redact", found: 0 } });

beforeEach(() => {
  reads.length = 0;
  refuse = null;
  events = [
    routine(5),
    ev(4, "llm_call", { name: "claude-sonnet-5-5" }),
    routine(3),
    ev(2, "guardrail", { name: "pii", payload: { guardrail: "pii", blocked: true, detail: "blocked a card number" } }),
  ];
});

const rows = () => screen.getAllByRole("button", { name: "trace" }).length;

describe("the routine guardrail checks", () => {
  it("are hidden by default, counted on a chip; a check that blocked still shows", async () => {
    render(<Theme><ActivityStreamPanel onOpenTrace={() => {}} /></Theme>);
    const chip = await screen.findByTestId("stream-routine");
    expect(chip).toHaveTextContent("2 routine PII checks hidden · show");
    expect(rows()).toBe(2); // the model call and the block
    // The route cannot leave a kind out, so the backfill reads deeper while they are hidden.
    expect(reads[0]).toMatchObject({ limit: 300 });

    fireEvent.click(chip);
    await vi.waitFor(() => expect(rows()).toBe(4));
    expect(screen.getByTestId("stream-routine")).toHaveTextContent("routine checks shown · hide");
    expect(reads.at(-1)).toMatchObject({ limit: 100 });
  });

  it("show when the guardrail kind is asked for by name", async () => {
    render(<Theme><ActivityStreamPanel onOpenTrace={() => {}} /></Theme>);
    await screen.findByTestId("stream-routine");
    fireEvent.click(screen.getByRole("button", { name: /^guardrail · 3$/ }));
    await vi.waitFor(() => expect(rows()).toBe(4));
    expect(screen.queryByTestId("stream-routine")).toBeNull();
  });

  it("leave a line that says so when nothing else is in the tail", async () => {
    events = [routine(2), routine(1)];
    render(<Theme><ActivityStreamPanel /></Theme>);
    expect(await screen.findByText("Only routine PII checks among the newest 2 events.")).toBeInTheDocument();
    expect(screen.queryByText(/Quiet — recording is on/)).toBeNull();
  });

  it("are told apart from a block the way the governance feed tells them: blocked in the payload, or a failed event", () => {
    expect(isRoutineCheck(routine(1))).toBe(true);
    expect(isRoutineCheck(ev(1, "guardrail", { payload: { blocked: true } }))).toBe(false);
    expect(isRoutineCheck(ev(1, "guardrail", { ok: false }))).toBe(false);
    expect(isRoutineCheck(ev(1, "llm_call"))).toBe(false);
  });

  it("say a read that failed, never the quiet 'recording is on' line", async () => {
    refuse = "Reading the log failed (503)";
    events = [];
    render(<Theme><ActivityStreamPanel /></Theme>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Reading the log failed (503)");
    expect(screen.queryByText(/Quiet — recording is on/)).toBeNull();
  });
});
