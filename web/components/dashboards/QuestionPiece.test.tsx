// @vitest-environment jsdom
/**
 * A Question on a dashboard (PENDING 54; design-mockups/dashboard-questions.html): its latest answer as the Data Canvas
 * shows one, every earlier answer, and the cost said beside it. Reading it asks nothing; asking costs a run, so it asks
 * once more before it spends.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { DashboardQuestion } from "@/lib/api";
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";

const api = vi.hoisted(() => ({ readQuestion: vi.fn(), askQuestionNow: vi.fn(), getMetrics: vi.fn() }));
vi.mock("@/lib/api", async original => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const nav = vi.hoisted(() => ({ requestTab: vi.fn() }));
vi.mock("@/lib/navigate", async original => ({ ...(await original<typeof import("@/lib/navigate")>()), ...nav }));

const { QuestionPiece, costWords } = await import("@/components/dashboards/QuestionPiece");

const COST = { kind: "", from: "the install's own 12 metered runs", tokens: 410000, minutes: 6.2, n: 12,
               usd_floor: 0.38, usd_n: 9, unpriced_calls: 0, ceiling: {} };

// theLook's daily question, as its runs of 22 and 23 October answered it (the mockup's own figures)
const DAILY: DashboardQuestion = {
  automation_id: "aut-daily-1", question: "What changed in theLook in the last day?", rhythm: "daily",
  rhythm_words: "Daily · 09:00 UTC", next_at: "2026-10-24T09:00:00+00:00", enabled: true, running: false, cost: COST,
  latest: {
    id: "1008d310", headline: "Revenue rose $774.33 on 15 Oct to $16,907.77; Outerwear & Coats led the gain",
    summary: "Revenue on 15 Oct was $16,907.77 on 279 orders, up $774.33 on the day before.",
    figures: [{ label: "Revenue, 15 Oct", value: "$16,907.77", note: "279 orders" }],
    why: { drivers: [], lines: ["Outerwear & Coats at +$1,314.50 is the largest contributor"] },
    gaps: "Why Outerwear rose was not tested.", confidence: "MEDIUM", period: "2026-10-15", against: "2026-10-14 (previous day)",
    asked_at: "2026-10-23T09:00:59+00:00", answered_at: "2026-10-23T09:07:10+00:00", minutes: 6.2,
  },
  answers: [
    { id: "1008d310", asked_at: "2026-10-23T09:00:59+00:00", answered_at: "2026-10-23T09:07:10+00:00", status: "complete",
      headline: "Revenue rose $774.33 on 15 Oct", verdict: "answered" },
    { id: "74b87b43", asked_at: "2026-10-22T16:50:00+00:00", answered_at: "2026-10-22T16:56:00+00:00", status: "complete",
      headline: "Revenue on 2026-10-14 rose 62.73% day-over-day to $97,274.71", verdict: "contradicted" },
  ],
};

beforeEach(() => { api.readQuestion.mockReset(); api.askQuestionNow.mockReset(); nav.requestTab.mockReset(); });

describe("a question on a dashboard", () => {
  it("offers Decide under its latest answer, on the dashboard's connection, citing that answer's run", async () => {
    api.readQuestion.mockResolvedValue(DAILY);
    api.getMetrics.mockResolvedValue([]);
    render(<QuestionPiece automation="aut-daily-1" connectionId="thelook" />);
    const door = await screen.findByTestId("question-decide");
    expect(await within(door).findByRole("button", { name: "Decide" })).toBeInTheDocument();
  });

  it("shows its latest answer as the Data Canvas does, and reading it asks nothing", async () => {
    api.readQuestion.mockResolvedValue(DAILY);
    render(<QuestionPiece automation="aut-daily-1" />);
    expect(await screen.findByText(DAILY.latest!.headline)).toBeInTheDocument();
    expect(screen.getByTestId("question-text")).toHaveTextContent("What changed in theLook in the last day?");
    expect(screen.getByText("Daily · 09:00 UTC")).toBeInTheDocument();
    expect(screen.getByTestId("question-dated")).toHaveTextContent(
      "Answered Fri 23 Oct at 09:07 UTC, for 2026-10-15 against 2026-10-14 (previous day).");
    expect(screen.getByTestId("question-figures")).toHaveTextContent("Revenue, 15 Oct$16,907.77279 orders");
    expect(screen.getByTestId("question-why-lines")).toHaveTextContent("Outerwear & Coats at +$1,314.50 is the largest contributor");
    expect(screen.getByTestId("question-gaps")).toHaveTextContent("Why Outerwear rose was not tested.");
    expect(screen.getByTestId("question-cost")).toHaveTextContent(
      "Each answer is a full agent run — about 6 min on this install, at least $0.38 · about 30 runs a month");
    expect(api.readQuestion).toHaveBeenCalledWith("aut-daily-1", undefined);
    expect(api.askQuestionNow).not.toHaveBeenCalled();
  });

  it("lists the earlier answers with their verdicts — a contradicted one says so", async () => {
    api.readQuestion.mockResolvedValue(DAILY);
    render(<QuestionPiece automation="aut-daily-1" />);
    const earlier = await screen.findByTestId("question-earlier");
    expect(earlier).toHaveTextContent("Thu 22 Oct");
    expect(earlier).toHaveTextContent("contradicted");
    expect(earlier).not.toHaveTextContent("Revenue rose $774.33 on 15 Oct");     // the latest is drawn above, once
    fireEvent.click(screen.getByText("Revenue on 2026-10-14 rose 62.73% day-over-day to $97,274.71"));
    expect(nav.requestTab).toHaveBeenCalledWith("chat", { run: "74b87b43" });
  });

  it("asks again only after a second click, and says what happened", async () => {
    api.readQuestion.mockResolvedValue(DAILY);
    api.askQuestionNow.mockResolvedValue({ outcome: "fired", reason: "", asked: true, message: "" });
    render(<QuestionPiece automation="aut-daily-1" />);
    fireEvent.click(await screen.findByTestId("question-ask"));
    expect(api.askQuestionNow).not.toHaveBeenCalled();
    expect(screen.getByText("This asks the agent now — a full run.")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("question-ask-confirm"));
    await waitFor(() => expect(api.askQuestionNow).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId("question-asked")).toHaveTextContent("Asked. The answer is kept here when the run finishes");
  });

  it("before its first answer, says when it comes — or that it is asked only when you ask", async () => {
    api.readQuestion.mockResolvedValue({ ...DAILY, rhythm: "weekly", rhythm_words: "Weekly · Mondays 09:00 UTC",
      next_at: "2026-10-26T09:00:00+00:00", latest: null, answers: [] });
    const view = render(<QuestionPiece automation="aut-weekly-1" />);
    expect(await screen.findByTestId("question-waiting")).toHaveTextContent("No answer yet. The first comes Mon 26 Oct at 09:00 UTC");
    expect(screen.getByTestId("question-cost")).toHaveTextContent("about 4 runs a month");
    view.unmount();
    api.readQuestion.mockResolvedValue({ ...DAILY, rhythm: "ask", rhythm_words: "Only when asked", next_at: null, latest: null, answers: [] });
    render(<QuestionPiece automation="aut-ask-1" />);
    expect(await screen.findByTestId("question-waiting")).toHaveTextContent("No answer yet. It is asked only when you ask.");
  });
});

describe("what an answer costs, in words", () => {
  it("is this install's own measure — and says so when nothing has been metered or the model is unpriced", () => {
    expect(costWords({ ...COST, n: 0, minutes: null, usd_floor: null }, "monthly"))
      .toBe("Each answer is a full agent run — not yet metered on this install · 1 run a month");
    expect(costWords({ ...COST, usd_floor: null, unpriced_calls: 3 }, "ask"))
      .toBe("Each answer is a full agent run — about 6 min on this install, its model unpriced · a run each time it is asked");
  });
});
