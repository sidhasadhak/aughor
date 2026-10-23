// @vitest-environment jsdom
/** Keeping a question (PENDING 54, screen 2 of the approved mockup): Weekly by default, its period and its cost said
 *  before anything is kept, and nothing asked. */
import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/lib/testing";

const api = vi.hoisted(() => ({ keepQuestion: vi.fn(), readQuestionCost: vi.fn() }));
vi.mock("@/lib/api", async original => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const { QuestionComposer } = await import("@/components/dashboards/QuestionComposer");

const COST = { kind: "", from: "", tokens: 400000, minutes: 6.4, n: 5, usd_floor: null, usd_n: 0, unpriced_calls: 0, ceiling: {} };

describe("keeping a question", () => {
  it("is weekly by default, says its period and cost, and keeps exactly what was chosen", async () => {
    api.readQuestionCost.mockResolvedValue(COST);
    api.keepQuestion.mockResolvedValue({ automation_id: "aut-1", session: "question:x", first: "d4039693", rhythm: "monthly" });
    const onKept = vi.fn();
    render(<QuestionComposer connectionId="8233e4fd" question="Why did revenue change last month, against the month before?"
      firstRun="d4039693" onKept={onKept} onClose={() => {}} />);
    expect(screen.getByTestId("question-period")).toHaveTextContent("Mondays at 09:00 UTC, for the last complete week against the week before.");
    expect(await screen.findByText(/about 6 min on this install · about 4 runs a month\. The answer it is kept from is its first\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Monthly" }));
    expect(screen.getByTestId("question-period")).toHaveTextContent("The 1st of each month");
    fireEvent.click(screen.getByTestId("question-keep"));
    await waitFor(() => expect(onKept).toHaveBeenCalledWith("aut-1", "d4039693", "monthly"));
    expect(api.keepQuestion).toHaveBeenCalledWith("8233e4fd", { question: "Why did revenue change last month, against the month before?",
      rhythm: "monthly", schema_name: undefined, first_run: "d4039693" });
  });

  it("says why it was not kept, in the server's words", async () => {
    api.readQuestionCost.mockResolvedValue(COST);
    api.keepQuestion.mockRejectedValue(new Error("a question is at most 500 characters; this one is 612"));
    render(<QuestionComposer connectionId="c" question="x" onKept={() => {}} onClose={() => {}} />);
    fireEvent.click(screen.getByTestId("question-keep"));
    expect(await screen.findByRole("alert")).toHaveTextContent("a question is at most 500 characters; this one is 612");
  });
});
