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
    leadDetail: vi.fn(async () => ({ summary: "More orders, smaller ones.", figure: null, confidence: "HIGH", why: "" })),
    readYou: vi.fn(async () => ({ principal: "user:amit", n: 0, by_kind: {}, predictions: { scored: 0, inside: 0, coverage_observed: null } })),
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
  getMyAccess: vi.fn(async () => ({ user_id: null, actor: "amit", signed_in: false, org_id: "default", roles: [], permissions: [] })),
}));

import { SCHEDULED_HEADER, type Analysis } from "@/lib/home";
import { forgetMe } from "@/lib/useMe";
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
    forgetMe();
  });

  it("leads with the move, asks the question, and offers the finding — each from its record", async () => {
    render(<HomeDesk connectionId="c1" analyses={ANALYSES} onOpenAnalysis={() => {}} onDraft={() => {}} />);
    // an analysis holding no baseline figure is led by its headline; its summary stays in the analysis (CLARITY)
    expect(screen.getByTestId("home-lead")).toHaveTextContent("Revenue decreased 15.0% on September 27");
    await waitFor(() => expect(screen.getByTestId("home-lead")).toHaveTextContent("Looked into on"));
    expect(screen.queryByText(/More orders, smaller ones\./)).not.toBeInTheDocument();
    expect(screen.getByTestId("home-question")).toHaveTextContent("Did the team do anything that explains it?");
    expect(screen.getByTestId("home-question")).toHaveTextContent("August 2026 Revenue Increased by 13.2%");
    expect(await screen.findByText("Email drives the most unique user activity.")).toBeInTheDocument();
    // an empty section is one muted line
    expect(screen.getByTestId("home-standing")).toHaveTextContent("No question asked three times yet.");
    expect(screen.getByTestId("home-week")).toHaveTextContent("Nothing lands in the next seven days.");
  });

  it("leads with the figure when its analysis holds one: the value, its change and the baseline's verdict as chips", async () => {
    const { leadDetail } = await import("@/lib/home");
    vi.mocked(leadDetail).mockResolvedValueOnce({ summary: "", confidence: "MEDIUM", why: "a refutation challenged it",
      figure: { metric: "Revenue", day: "2026-10-02", value: "$19,087.76", change: "+$209.55", pct: 0.0111,
                verdict: "within normal range", unusual: false } });
    render(<HomeDesk connectionId="c1" analyses={ANALYSES} onOpenAnalysis={() => {}} onDraft={() => {}} />);
    expect(await screen.findByTestId("home-lead-value")).toHaveTextContent("$19,087.76");
    const lead = screen.getByTestId("home-lead");
    expect(lead).toHaveTextContent("Revenue · Fri 2 Oct");
    expect(lead).toHaveTextContent("+$209.55 · +1.1%");
    expect(lead).toHaveTextContent("within normal range");
    // a conclusion below high confidence says so beside the figure, with why on hover
    expect(screen.getByText("medium confidence")).toHaveAttribute("title", "a refutation challenged it");
  });

  it("books a person's answer about the analysis that asked it, without asking their name", async () => {
    render(<HomeDesk connectionId="c1" analyses={ANALYSES} onOpenAnalysis={() => {}} onDraft={() => {}} />);
    // who the answer is recorded as is the server's word, shown — there is no name to type
    expect(await screen.findByText("amit")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("your name")).not.toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "A campaign" })); });
    await waitFor(() => expect(booked).toHaveLength(1));
    expect(booked[0]).toMatchObject({ connection_id: "c1", text: "A campaign", about: "aug" });
    expect(booked[0]).not.toHaveProperty("by");
    expect(screen.getByTestId("home-question")).toHaveTextContent("Kept as said by you");
  });

  it("drafts a follow-up into the ask box rather than sending it", () => {
    const onDraft = vi.fn();
    render(<HomeDesk connectionId="c1" analyses={ANALYSES} onOpenAnalysis={() => {}} onDraft={onDraft} />);
    fireEvent.click(screen.getByRole("button", { name: "Ask a follow-up" }));
    expect(onDraft).toHaveBeenCalledWith(expect.stringContaining("Revenue decreased 15.0%"));
  });
});
