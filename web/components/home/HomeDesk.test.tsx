// @vitest-environment jsdom
/**
 * Home's desk renders its sections from records, and a person's answer is booked as theirs.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const booked: unknown[] = [];

vi.mock("@/lib/home", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/home")>();
  return {
    ...real,
    domainFindings: vi.fn(async () => [
      { id: "f1", text: "Email drives the most unique user activity.", domain: "Key Questions", generated_at: "2026-09-27" },
    ]),
    bookSaid: vi.fn(async (body: unknown) => { booked.push(body); return {}; }),
    readYou: vi.fn(async () => ({ principal: "person:Amit", n: 0, by_kind: {}, predictions: { scored: 0, inside: 0, coverage_observed: null } })),
    dismissFinding: vi.fn(async () => undefined),
    recheckFinding: vi.fn(async () => ({ status: "confirmed" })),
  };
});
vi.mock("@/lib/record", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/record")>()),
  listClaims: vi.fn(async () => []),
  listDecisions: vi.fn(async () => []),
  declareDecision: vi.fn(async () => ({ review_on: "2026-11-06" })),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getAnalysisSummary: vi.fn(async () => ({ headline: "", summary: "More orders, smaller ones." })),
}));

import { SCHEDULED_HEADER, type Analysis } from "@/lib/home";
import { HomeDesk } from "./HomeDesk";

const ANALYSES: Analysis[] = [
  { id: "r27", started_at: "2026-10-05T09:01:00Z", status: "complete", connection_id: "c1",
    question: `${SCHEDULED_HEADER}\n\nWhat changed?`,
    headline: "Revenue decreased 15.0% on September 27, 2026, alongside a 23.2% decline in average order value." },
  { id: "aug", started_at: "2026-10-05T21:16:00Z", status: "complete", connection_id: "c1", question: "Why did revenue move?",
    headline: "August 2026 Revenue Increased by 13.2% Driven by Search Traffic and Men's Department Growth" },
];

describe("HomeDesk", () => {
  beforeEach(() => {
    booked.length = 0;
    window.localStorage.setItem("aughor_record_actor", "Amit");
  });

  it("leads with the move, asks the question, and offers the finding — each from its record", async () => {
    render(<HomeDesk connectionId="c1" analyses={ANALYSES} onOpenAnalysis={() => {}} onDraft={() => {}} />);
    expect(screen.getByTestId("home-lead")).toHaveTextContent("Revenue decreased 15.0% on September 27");
    expect(await screen.findByText(/More orders, smaller ones\./)).toBeInTheDocument();
    expect(screen.getByTestId("home-question")).toHaveTextContent("Did the team do anything that explains it?");
    expect(await screen.findByText("Email drives the most unique user activity.")).toBeInTheDocument();
    expect(screen.getByText(/No question has been asked here three times yet/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing on the record lands in the next seven days/)).toBeInTheDocument();
  });

  it("books a person's answer about the analysis that asked it", async () => {
    render(<HomeDesk connectionId="c1" analyses={ANALYSES} onOpenAnalysis={() => {}} onDraft={() => {}} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "A campaign" })); });
    await waitFor(() => expect(booked).toHaveLength(1));
    expect(booked[0]).toMatchObject({ connection_id: "c1", text: "A campaign", about: "aug", by: "Amit" });
    expect(screen.getByTestId("home-question")).toHaveTextContent("Kept as said by you");
  });

  it("drafts a follow-up into the ask box rather than sending it", () => {
    const onDraft = vi.fn();
    render(<HomeDesk connectionId="c1" analyses={ANALYSES} onOpenAnalysis={() => {}} onDraft={onDraft} />);
    fireEvent.click(screen.getByRole("button", { name: "Ask a follow-up" }));
    expect(onDraft).toHaveBeenCalledWith(expect.stringContaining("Revenue decreased 15.0%"));
  });
});
