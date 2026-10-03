// @vitest-environment jsdom
/**
 * FL-5 — each answered sub-question lands as prose while the run works. (The progress
 * card these tests also covered is gone: the thinking row carries the latest update.)
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPTY_TURN, type ChatTurn } from "@/lib/chatTurn";
import type { SubQuestion, SubQuestionAnswer } from "@/lib/types";

import { InFlightFindings } from "./RunProgressCard";

const answer = (id: string, text: string) =>
  ({ subq_id: id, question: `q-${id}`, answer: text } as unknown as SubQuestionAnswer);
const planned = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ id: `s${i}` } as unknown as SubQuestion));

function turn(over: Partial<ChatTurn>): ChatTurn {
  return { ...EMPTY_TURN, id: "t1", question: "q", mode: "ask", ...over };
}

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
