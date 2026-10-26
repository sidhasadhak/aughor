// @vitest-environment jsdom
/**
 * The Decide door on what a person reads (the decision-framework study §3.2, §8 step 3): one button, then what was
 * decided and what it should move; the server cites what it was taken on — a run's answer, or a Briefing figure for
 * its edition's days. With the decision loop off, or nowhere to book it, the door is not shown.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Theme } from "@radix-ui/themes";

import { fireEvent, render, screen, waitFor } from "@/lib/testing";

const api = vi.hoisted(() => ({ getSystemFlags: vi.fn(), getMetrics: vi.fn() }));
vi.mock("@/lib/api", async original => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const rec = vi.hoisted(() => ({ declareDecision: vi.fn() }));
vi.mock("@/lib/record", async original => ({ ...(await original<typeof import("@/lib/record")>()), ...rec }));
const nav = vi.hoisted(() => ({ requestTab: vi.fn() }));
vi.mock("@/lib/navigate", async original => ({ ...(await original<typeof import("@/lib/navigate")>()), ...nav }));

const { DecideDoor, forgetDecisionLoop } = await import("@/components/decisions/DecideDoor");

/** Choose a select's option the way a keyboard does (a Radix select, as Home's test drives it). */
function choose(label: string, value: string) {
  fireEvent.keyDown(screen.getByLabelText(label), { key: "ArrowDown" });
  const option = screen.getAllByRole("option").find(o => o.getAttribute("data-value") === value);
  if (!option) throw new Error(`${label} offers no ${value}`);
  fireEvent.keyDown(option, { key: "Enter" });
}
function offered(label: string): (string | null)[] {
  const trigger = screen.getByLabelText(label);
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  const values = screen.getAllByRole("option").map(o => o.getAttribute("data-value"));
  fireEvent.keyDown(trigger, { key: "Escape" });
  return values;
}

const BOOKED = { id: "dec-1", review_on: "2026-11-25", relied_on: ["claim-1"], extra: {} };

beforeEach(() => {
  forgetDecisionLoop();
  api.getSystemFlags.mockReset().mockResolvedValue({ "record.decision_loop": { value: true } });
  api.getMetrics.mockReset().mockResolvedValue([
    { name: "gmv", label: "GMV", status: "approved", time_kind: "flow", time_column: "orders.order_date", dimensions: ["platform"] },
    { name: "draft_one", label: "Draft", status: "draft", time_kind: "flow", time_column: "orders.order_date" },
  ]);
  rec.declareDecision.mockReset().mockResolvedValue(BOOKED);
  nav.requestTab.mockReset();
});

describe("the Decide door", () => {
  it("books a decision on a run's answer, naming the run for the server to cite", async () => {
    render(<Theme><DecideDoor connectionId="c1" question="What did paid social bring?" on={{ kind: "run", runId: "inv-3" }} testId="d" /></Theme>);
    fireEvent.click(await screen.findByRole("button", { name: "Decide" }));
    fireEvent.change(screen.getByLabelText("What was decided"), { target: { value: "pause paid social" } });
    await screen.findByLabelText("The metric it should move");
    // only approved metrics that know their dates can be expected
    await waitFor(() => expect(offered("The metric it should move")).toEqual(["", "gmv"]));
    choose("The metric it should move", "gmv");
    fireEvent.click(screen.getByRole("button", { name: "Book it" }));
    await waitFor(() => expect(rec.declareDecision).toHaveBeenCalled());
    expect(rec.declareDecision.mock.calls[0][0]).toEqual({
      question: "What did paid social bring?", chosen: "pause paid social", options: ["pause paid social", "not act"],
      connection_id: "c1", note: "Decided on the answer of run inv-3", run_id: "inv-3",
      expectation: { metric: "gmv", direction: "up" },
    });
    expect(await screen.findByText(/Booked as a decision · review .* · it cites what it was decided on/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open it →" }));
    expect(nav.requestTab).toHaveBeenCalledWith("decisions", { id: "dec-1" });
  });

  it("books a decision on one of an edition's figures, for the edition's days, and says when nothing was cited", async () => {
    rec.declareDecision.mockResolvedValue({ ...BOOKED, relied_on: [], extra: { relied_on_note: "2030-01-01 to 2030-01-07 holds no rows of GMV" } });
    render(<Theme><DecideDoor connectionId="c1" question="Week 32" testId="d"
      on={{ kind: "figure", start: "2026-08-03", end: "2026-08-10", figures: [{ metric: "gmv", label: "GMV" }, { metric: "aov", label: "AOV" }] }} /></Theme>);
    fireEvent.click(await screen.findByRole("button", { name: "Decide" }));
    choose("The figure it was decided on", "aov");
    fireEvent.change(screen.getByLabelText("What was decided"), { target: { value: "raise the threshold" } });
    fireEvent.click(screen.getByRole("button", { name: "Book it" }));
    await waitFor(() => expect(rec.declareDecision).toHaveBeenCalled());
    const body = rec.declareDecision.mock.calls[0][0];
    expect(body.question).toBe("Week 32 — AOV");
    expect(body.figure).toEqual({ metric: "aov", start: "2026-08-03", end: "2026-08-10" });
    expect(body.expectation).toBeUndefined();
    expect(await screen.findByText(/holds no rows of GMV · nothing expected, so it cannot be scored/)).toBeInTheDocument();
  });

  it("is not shown with the decision loop off, or with nowhere to book it", async () => {
    api.getSystemFlags.mockResolvedValue({ "record.decision_loop": { value: false } });
    const { container } = render(<Theme><DecideDoor connectionId="c2" question="q" on={{ kind: "run", runId: "r" }} testId="d" /></Theme>);
    await waitFor(() => expect(api.getSystemFlags).toHaveBeenCalled());
    expect(container.querySelector("[data-testid='d']")).toBeNull();
    api.getSystemFlags.mockClear();
    forgetDecisionLoop();
    const none = render(<Theme><DecideDoor connectionId="" question="q" on={{ kind: "run", runId: "r" }} testId="d2" /></Theme>);
    expect(none.container.querySelector("[data-testid='d2']")).toBeNull();
    expect(api.getSystemFlags).not.toHaveBeenCalled();
  });
});
