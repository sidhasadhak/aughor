// @vitest-environment jsdom
/**
 * The Agent's thinking row, at the user's word (2026-09-29):
 *
 *   - it stays CLOSED while the turn runs, and shows only the step in hand — replaced as
 *     the next one starts — instead of a tree that grows and pushes the answer down;
 *   - it ends as "Thought process", still closed, and opens by hand to the steps;
 *   - the "Found relevant data" row of table chips is gone: each query in the trace opens
 *     its own SQL and rows.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { ChatMessage } from "@/components/ChatMessage";
import { EMPTY_TURN, type ChatTurn, type InvPhase } from "@/lib/chatTurn";

const phase = (id: string, status: string, summary = ""): InvPhase => ({
  phase_id: id, phase_name: id, phase_icon: "", status, summary,
  findings: [], skipped_reason: null, caveats: [],
} as unknown as InvPhase);

// The Agent's turn is spelled on the wire with the backend's word, and a turn built by hand
// has to say it. Once, here — every turn below takes it from this.
const AGENT: ChatTurn["mode"] = "investigate";

const turn = (over: Partial<ChatTurn>): ChatTurn => ({
  ...EMPTY_TURN, id: "t1", question: "What was total revenue in July 2026?",
  mode: AGENT, queryMode: AGENT, ...over,
} as ChatTurn);

const RUNNING = turn({
  status: "loading",
  phases: [
    phase("baseline", "complete", "Revenue rose against the prior period."),
    phase("decompose", "running"),
  ],
});

const DONE = turn({
  status: "done", tablesUsed: ["order_items", "products"],
  phases: [
    phase("baseline", "complete", "Revenue rose against the prior period."),
    phase("decompose", "complete", "Order volume carries the rise."),
  ],
});

// The answer's body prints a phase's summary too, so every assertion about the ROW is made
// inside the row.
const row = () => within(screen.getByRole("group", { name: "Thought process" }));
const toggle = () => row().getByRole("button");

describe("the thinking row", () => {
  it("is closed while the turn runs and shows only the step in hand", async () => {
    render(<ChatMessage turn={RUNNING} />);
    expect(row().getByText("Thinking…")).toBeInTheDocument();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    // typed out a character at a time, as a live step is
    expect(await row().findByText("Breaking the metric into its drivers", {}, { timeout: 4000 }))
      .toBeInTheDocument();
    // the finished step is in the trace, not on the row
    expect(row().queryByText("Revenue rose against the prior period.")).not.toBeInTheDocument();
    expect(row().queryByText("Agent")).not.toBeInTheDocument();
  });

  it("shows the conclusion that landed last while nothing more specific is running", () => {
    // The analyst's phases arrive COMPLETE; between them the only running step is the
    // trailing "Analysing the data…", which is running for the whole turn.
    render(<ChatMessage turn={turn({
      status: "loading",
      phases: [phase("baseline", "complete", "Revenue rose against the prior period."),
               phase("decompose", "complete", "Order volume carries the rise.")],
    })} />);
    expect(row().getByText("Order volume carries the rise.")).toBeInTheDocument();
    expect(row().queryByText("Revenue rose against the prior period.")).not.toBeInTheDocument();
    expect(row().queryByText("Analysing the data…")).not.toBeInTheDocument();
  });

  it("falls back to the placeholder when no phase has landed yet", async () => {
    render(<ChatMessage turn={turn({ status: "loading", phases: [] })} />);
    expect(await row().findByText(/Decomposing question…|Analysing the data…/, {}, { timeout: 4000 }))
      .toBeInTheDocument();
  });

  it("shows the question being classified before a route is known", async () => {
    render(<ChatMessage turn={turn({ status: "loading", queryMode: null as never, phases: [] })} />);
    expect(await row().findByText("Classifying question…", {}, { timeout: 4000 })).toBeInTheDocument();
  });

  it("opens by hand mid-run to the whole trace, and the row's single line gives way to it", async () => {
    render(<ChatMessage turn={RUNNING} />);
    fireEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(row().getByText("Revenue rose against the prior period.")).toBeInTheDocument();
    expect(await row().findAllByText("Breaking the metric into its drivers", {}, { timeout: 4000 }))
      .toHaveLength(1);
  });

  it("ends as Thought process, closed, and opens by hand to the steps", () => {
    render(<ChatMessage turn={DONE} />);
    expect(row().getByText("Thought process")).toBeInTheDocument();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
    expect(screen.queryByText("Thinking complete")).not.toBeInTheDocument();
    expect(row().queryByText("Order volume carries the rise.")).not.toBeInTheDocument();

    fireEvent.click(toggle());
    expect(row().getByText("Revenue rose against the prior period.")).toBeInTheDocument();
    expect(row().getByText("Order volume carries the rise.")).toBeInTheDocument();
  });

  it("closes a trace that was opened by hand the moment the turn stops running", () => {
    const { rerender } = render(<ChatMessage turn={RUNNING} />);
    fireEvent.click(toggle());
    expect(row().getByText("Revenue rose against the prior period.")).toBeInTheDocument();
    rerender(<ChatMessage turn={DONE} />);
    expect(row().getByText("Thought process")).toBeInTheDocument();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(row().queryByText("Revenue rose against the prior period.")).not.toBeInTheDocument();
  });
});

describe("the finished answer", () => {
  it("does not list the tables it read as a row of its own", () => {
    render(<ChatMessage turn={DONE} />);
    expect(screen.queryByText(/Found relevant data/)).not.toBeInTheDocument();
    expect(screen.queryByText("order_items")).not.toBeInTheDocument();
  });
});
