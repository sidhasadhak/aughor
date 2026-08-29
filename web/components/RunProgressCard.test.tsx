// @vitest-environment jsdom
/**
 * FL-5 — the progress card renders only what the stream actually said: the
 * activity line, a bar ONLY when a real denominator exists, counts that are
 * nonzero, and the children slot (the transport notices). jsdom is enough
 * here because everything asserted is structure the component hands the DOM,
 * not geometry.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPTY_TURN, type ChatTurn } from "@/lib/chatTurn";
import type { SubQuestion, SubQuestionAnswer } from "@/lib/types";

import { InFlightFindings, RunProgressCard } from "./RunProgressCard";

const answer = (id: string, text: string) =>
  ({ subq_id: id, question: `q-${id}`, answer: text } as unknown as SubQuestionAnswer);
const planned = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ id: `s${i}` } as unknown as SubQuestion));

function turn(over: Partial<ChatTurn>): ChatTurn {
  return { ...EMPTY_TURN, id: "t1", question: "q", mode: "ask", ...over };
}

describe("RunProgressCard", () => {
  it("renders the activity line, a real-denominator bar, and the counts", () => {
    render(
      <RunProgressCard
        turn={turn({
          statusText: "Scanning region · 3/8…",
          scanProgress: { done: 3, total: 8 },
          scanItems: ["segment", "region"],
          queriesExecuted: [
            { sql: "SELECT 1", row_count: 1, error: null },
            { sql: "SELECT 2", row_count: 2, error: null },
          ],
          guardReceipts: [{ guard: "g", action: "a", detail: "d" }],
        })}
      />,
    );
    expect(screen.getByText("Scanning region · 3/8…")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemax", "8");
    expect(
      screen.getByText("2 queries · 3/8 dimensions · region in progress · 1 guard fired"),
    ).toBeInTheDocument();
  });

  it("falls back to the sub-question plan as the denominator", () => {
    render(
      <RunProgressCard
        turn={turn({
          subQuestions: planned(3),
          subqAnswers: [answer("s0", "East looks flat.")],
        })}
      />,
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "1");
    expect(bar).toHaveAttribute("aria-valuemax", "3");
    expect(screen.getByText("1/3 sub-questions")).toBeInTheDocument();
  });

  it("draws NO bar without a denominator — no fake motion", () => {
    render(<RunProgressCard turn={turn({ statusText: "Working…" })} />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByText("Working…")).toBeInTheDocument();
  });

  it("hosts its children — the transport notices ride inside the card", () => {
    render(
      <RunProgressCard turn={turn({})}>
        <p>gemini didn’t respond — continuing with groq.</p>
      </RunProgressCard>,
    );
    expect(screen.getByText(/continuing with groq/)).toBeInTheDocument();
  });
});

describe("InFlightFindings", () => {
  it("each answered sub-question lands as prose while the run works", () => {
    render(
      <InFlightFindings
        turn={turn({
          subqAnswers: [answer("s1", "East looks flat."), answer("s2", "South is down 4%.")],
        })}
      />,
    );
    expect(screen.getByText("East looks flat.")).toBeInTheDocument();
    expect(screen.getByText("South is down 4%.")).toBeInTheDocument();
  });

  it("renders nothing once the terminal report owns the findings, or with nothing to say", () => {
    const { container } = render(
      <InFlightFindings
        turn={turn({
          subqAnswers: [answer("s1", "East looks flat.")],
          exploreReport: { summary: "done" } as unknown as ChatTurn["exploreReport"],
        })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    const empty = render(<InFlightFindings turn={turn({})} />);
    expect(empty.container).toBeEmptyDOMElement();
  });
});
