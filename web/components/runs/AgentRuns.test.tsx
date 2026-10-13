// @vitest-environment jsdom
/**
 * Agent runs, laid out to CLARITY: four figures read from the run list, the runs that need a person first, then one
 * row per question — its repeats folded into ×N with the latest headline, the earlier runs one click away. A completed
 * run wears no mark; a run that kept no headline says so in words, never a dash. A read that failed says so.
 *
 * Every read goes through `fetch`, answered here — nothing reaches the live API from jsdom.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { beforeEach, describe, expect, it, vi } from "vitest";

let onEvent: (() => void) | null = null;
vi.mock("@/lib/events", () => ({
  subscribeKernelEvents: (cb: () => void) => { onEvent = cb; return () => { onEvent = null; }; },
}));

import { AgentRuns, foldRuns, type Run } from "./AgentRuns";

const SCHEDULED = (day: string) =>
  `[Scheduled-run context — written by code, not inferred]\nThis is a scheduled daily run at ${day}T09:00Z.\n\nWhat changed in theLook in the last day? Give me the top three findings with the numbers.`;

let list: unknown;
const urls: string[] = [];
globalThis.fetch = (async (input: RequestInfo | URL) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  urls.push(url);
  const p = new URL(url, "http://x").pathname;
  const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });
  if (p === "/connections") return json([{ id: "8233e4fd", name: "theLook" }]);
  return list instanceof Error ? json({ detail: "down" }, 503) : json(list);
}) as typeof fetch;

const run = (id: string, over: Partial<Run> = {}): Run => ({
  id, question: "What was total revenue in July 2026?", headline: `Headline of ${id}`, status: "complete",
  kind: "investigation", connection_id: "8233e4fd", canvas_id: null, started_at: "2026-10-10T09:00:00Z", ...over,
});

const opened: unknown[][] = [];
const asked: (string | undefined)[] = [];
const mount = () => render(<Theme><AgentRuns onGoToChat={q => asked.push(q)} onOpenRun={(...a) => opened.push(a)}
  onOpenMachineView={() => {}} workspaceId="default" /></Theme>);

beforeEach(() => {
  urls.length = 0; opened.length = 0; asked.length = 0;
  list = [
    run("rev3", { started_at: "2026-10-12T10:00:00Z", headline: "July revenue was $231.5K" }),
    run("rev2", { started_at: "2026-10-11T10:00:00Z", headline: null }),
    run("rev1", { started_at: "2026-10-10T10:00:00Z", status: "failed", headline: null }),
    run("d2", { question: SCHEDULED("2026-10-12"), started_at: "2026-10-12T09:00:00Z", headline: "Oct 4 revenue up 17.2%" }),
    run("d1", { question: SCHEDULED("2026-10-11"), started_at: "2026-10-11T09:00:00Z", headline: "Oct 3 revenue up 11.9%" }),
    run("late", { question: "What is causing delivery delays?", started_at: "2026-10-09T09:00:00Z", status: "timed_out", headline: null }),
    run("chat1", { kind: "chat", question: "How many orders yesterday?", started_at: "2026-10-08T09:00:00Z", headline: "49 orders" }),
  ];
});

describe("folding the run list", () => {
  it("folds the same question into one group, newest first, and a daily run however its date line reads", () => {
    const groups = foldRuns(list as Run[]);
    expect(groups.map(g => [g.title, g.runs.length])).toEqual([
      ["What is causing delivery delays?", 1],          // ended without an answer — first
      ["What was total revenue in July 2026?", 3],
      ["What changed in theLook in the last day? Give me the top three findings with the numbers.", 2],
      ["How many orders yesterday?", 1],
    ]);
    expect(groups[1].runs.map(r => r.id)).toEqual(["rev3", "rev2", "rev1"]);
    expect(groups[2].scheduled).toBe(true);
  });
});

describe("Agent runs", () => {
  it("opens on four figures read from the list", async () => {
    mount();
    const figures = await screen.findByTestId("runs-figures");
    expect(within(figures).getByTestId("runs-fig-runs-value")).toHaveTextContent("7");
    expect(within(figures).getByTestId("runs-fig-runs")).toHaveTextContent("since Thu 8 Oct · theLook");
    expect(within(figures).getByTestId("runs-fig-questions-value")).toHaveTextContent("4");
    expect(within(figures).getByTestId("runs-fig-questions")).toHaveTextContent("3 repeat runs folded");
    expect(within(figures).getByTestId("runs-fig-unfinished-value")).toHaveTextContent("2");
    expect(within(figures).getByTestId("runs-fig-running-value")).toHaveTextContent("0");
    // the page reads the newest runs and says so only when it hit the limit
    expect(urls.some(u => /limit=50&workspace_id=default/.test(u))).toBe(true);
    expect(within(figures).queryByText(/newest 50/)).toBeNull();
  });

  it("folds repeats into one row with ×N and the latest headline; the earlier runs open from the count", async () => {
    mount();
    const rows = await screen.findAllByTestId("run-group");
    expect(rows).toHaveLength(4);
    const revenue = rows.find(r => r.textContent?.includes("What was total revenue in July 2026?"))!;
    expect(revenue).toHaveTextContent("July revenue was $231.5K");
    expect(revenue).toHaveTextContent("1 earlier didn't finish");
    expect(within(revenue).queryByTestId("run-earlier")).toBeNull();
    fireEvent.click(within(revenue).getByRole("button", { name: /×3/ }));
    const earlier = within(revenue).getByTestId("run-earlier");
    expect(earlier).toHaveTextContent("no headline");
    expect(earlier).toHaveTextContent("failed");
    fireEvent.click(within(earlier).getAllByRole("button")[1]);
    expect(opened.at(-1)).toEqual(["rev1", "investigation", "8233e4fd", null]);
  });

  it("says only what did not complete — never 'Completed', never a dash", async () => {
    mount();
    const list = await screen.findByTestId("runs-list");
    expect(list.textContent).not.toMatch(/completed/i);
    expect(list.textContent).not.toContain("—");
    const marks = within(list).getAllByTestId("run-status").map(m => m.textContent);
    expect(marks).toEqual(["timed out"]);
    // the failed one leads the list
    expect(within(list).getAllByTestId("run-group")[0]).toHaveTextContent("What is causing delivery delays?");
  });

  it("puts a run that ended without an answer under Needs you, with Open and Ask again on its row", async () => {
    mount();
    const needs = await screen.findByTestId("runs-needs");
    const rows = within(needs).getAllByTestId("runs-needs-row");
    expect(rows).toHaveLength(1);   // the revenue question's failure was answered by a later run
    expect(rows[0]).toHaveTextContent("What is causing delivery delays?");
    expect(rows[0]).toHaveTextContent("timed out");
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Ask again" }));
    expect(asked).toEqual(["What is causing delivery delays?"]);
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Open" }));
    expect(opened.at(-1)).toEqual(["late", "investigation", "8233e4fd", null]);
  });

  it("names a scheduled question once and opens a conversation as a conversation", async () => {
    mount();
    const rows = await screen.findAllByTestId("run-group");
    const daily = rows.find(r => r.textContent?.includes("What changed in theLook in the last day?"))!;
    expect(daily).toHaveTextContent("Oct 4 revenue up 17.2%");
    expect(daily).toHaveTextContent("scheduled");
    expect(daily.textContent).not.toContain("Scheduled-run context");
    // a long question reads as its first sentence; the whole of it is on hover
    expect(daily.textContent).not.toContain("Give me the top three");
    expect(within(daily).getAllByRole("button")[0]).toHaveAttribute("title",
      "What changed in theLook in the last day? Give me the top three findings with the numbers.");
    fireEvent.click(screen.getByRole("radio", { name: /Conversations/ }));
    const chats = screen.getAllByTestId("run-group");
    expect(chats).toHaveLength(1);
    fireEvent.click(within(chats[0]).getAllByRole("button")[0]);
    expect(opened.at(-1)).toEqual(["chat1", "chat", "8233e4fd", null]);
  });

  it("says the list holds only the newest 50 when it is full", async () => {
    list = Array.from({ length: 50 }, (_, i) => run(`r${i}`, { question: `Question ${i}?`,
      started_at: `2026-10-${String(1 + (i % 9)).padStart(2, "0")}T0${i % 10}:00:00Z` }));
    mount();
    const figures = await screen.findByTestId("runs-figures");
    expect(within(figures).getByText("newest 50")).toBeInTheDocument();
  });

  it("names one connection once, in the figures — several on each row", async () => {
    mount();
    const rows = await screen.findAllByTestId("run-group");
    expect(rows.every(r => !r.textContent?.includes("theLook ·") && !r.textContent?.includes("· theLook"))).toBe(true);
    (list as Run[]).push(run("other", { question: "How many returns?", connection_id: "aaaa1111bbbb", started_at: "2026-10-12T11:00:00Z" }));
    onEvent?.();
    await vi.waitFor(() => expect(screen.getByTestId("runs-fig-runs")).toHaveTextContent("2 connections"));
    const other = screen.getAllByTestId("run-group").find(r => r.textContent?.includes("How many returns?"))!;
    expect(other).toHaveTextContent("connection aaaa1111");
  });

  it("refreshes when a run's event lands", async () => {
    mount();
    await screen.findByTestId("runs-figures");
    const before = urls.filter(u => u.includes("limit=")).length;
    onEvent?.();
    await vi.waitFor(() => expect(urls.filter(u => u.includes("limit=")).length).toBe(before + 1));
  });

  it("says a failed read and offers Retry — never an empty list", async () => {
    list = new Error("down");
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not read the runs");
    expect(screen.queryByText(/No runs yet/)).toBeNull();
  });

  it("with no runs, one line and a way to ask", async () => {
    list = [];
    mount();
    expect(await screen.findByText("No runs yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask a question" }));
    expect(asked).toEqual([undefined]);
  });
});
