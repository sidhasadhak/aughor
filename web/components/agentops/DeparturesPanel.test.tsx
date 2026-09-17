// @vitest-environment jsdom
/**
 * HB-2 — the departures screen: what left and what was held, and the two things a person
 * owes the ledger. Locked here: a held row shows its reason; a probation row's Review opens
 * the declarer's three marks and a mark reaches the door; an owner question offers its
 * readings and the chosen one reaches the door; a receipt's link opens its row.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Departure } from "@/lib/api";
import { normalizeDeparture } from "@/lib/departures";

const getDepartures = vi.fn();
const getDepartureSummary = vi.fn();
const markDeparture = vi.fn();
const answerDeparture = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getDepartures: (...a: unknown[]) => getDepartures(...a),
    getDepartureSummary: (...a: unknown[]) => getDepartureSummary(...a),
    markDeparture: (...a: unknown[]) => markDeparture(...a),
    answerDeparture: (...a: unknown[]) => answerDeparture(...a),
  };
});

const { DeparturesPanel } = await import("@/components/agentops/DeparturesPanel");

const dep = (over: Record<string, unknown>): Departure => normalizeDeparture({
  ts: "2026-09-17T09:00:12Z", kind: "slack_post", automation_name: "Dispatch promise watch",
  target: "sb_1:#ops", reasons: [], checks: {}, guards: {}, receipt: {}, question: {},
  verdict: "", answer: "", ...over,
});

const ROWS = [
  dep({ id: "held1", state: "held",
        reasons: ["re-measured at departure: 99,441 is not in promise dispatch of order_to_delivery"],
        checks: { remeasure: "99,441 not in promise dispatch" }, guards: { remeasure: "held" },
        receipt: { line: "Receipt: promise dispatch of order_to_delivery · departure held1" } }),
  dep({ id: "prob1", state: "held_probation", automation_name: "Morning anomalies",
        addressed_to: "user:ana",
        reasons: ["on probation: this departure goes to user:ana's review queue"] }),
  dep({ id: "ask1", state: "held_owner", automation_name: "Refund rate to Slack",
        question: { question: "“refund rate” can be computed two ways — which?",
                    readings: [{ label: "Governed: refund_rate", sql: "a" },
                               { label: "As I read the question", sql: "b" }],
                    previews: ["= 2.10%", "= 7.80%"] } }),
];

beforeEach(() => {
  getDepartures.mockReset().mockResolvedValue(ROWS);
  getDepartureSummary.mockReset().mockResolvedValue(
    { by_state: { held: 1, held_probation: 1, held_owner: 1 }, total: 3, awaiting: 2 });
  markDeparture.mockReset().mockResolvedValue({ departure: ROWS[1], graduated: false });
  answerDeparture.mockReset().mockResolvedValue({ departure: ROWS[2], resolutionId: "r1" });
  window.history.replaceState(null, "", "/");
});

describe("DeparturesPanel", () => {
  it("shows what was held and why, with what needs a person counted", async () => {
    render(<DeparturesPanel />);
    expect(await screen.findByText(/99,441 is not in promise dispatch/)).toBeInTheDocument();
    expect(screen.getByText("0 departed · 3 held · 2 need a person")).toBeInTheDocument();
    expect(screen.getByText("awaiting its declarer")).toBeInTheDocument();
    expect(screen.getByText("asking its owner")).toBeInTheDocument();
  });

  it("a declarer's mark reaches the door", async () => {
    const user = userEvent.setup();
    render(<DeparturesPanel />);
    await screen.findByText("Morning anomalies");
    const reviews = screen.getAllByRole("button", { name: "Review" });
    await user.click(reviews[0]);
    await user.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(markDeparture).toHaveBeenCalledWith("prob1", "accept"));
    expect(await screen.findByRole("status")).toHaveTextContent("Marked.");
  });

  it("an owner's chosen reading reaches the door", async () => {
    const user = userEvent.setup();
    render(<DeparturesPanel />);
    await screen.findByText("Refund rate to Slack");
    const reviews = screen.getAllByRole("button", { name: "Review" });
    await user.click(reviews[1]);
    expect(screen.getByText(/Nothing was sent/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "As I read the question = 7.80%" }));
    await waitFor(() => expect(answerDeparture).toHaveBeenCalledWith("ask1", "As I read the question"));
  });

  it("a receipt's link opens its row and is consumed", async () => {
    window.history.replaceState(null, "", "/?tab=agentic-ops&layer=departures&departure=held1");
    render(<DeparturesPanel />);
    expect(await screen.findByText("Receipt: promise dispatch of order_to_delivery · departure held1"))
      .toBeInTheDocument();
    expect(window.location.search).toBe("?tab=agentic-ops&layer=departures");
  });

  it("filters to what needs a person", async () => {
    const user = userEvent.setup();
    render(<DeparturesPanel />);
    await screen.findByText("Dispatch promise watch");
    await user.click(screen.getByRole("button", { name: "Needs a person" }));
    expect(screen.queryByText("Dispatch promise watch")).not.toBeInTheDocument();
    expect(screen.getByText("Morning anomalies")).toBeInTheDocument();
  });
});
