// @vitest-environment jsdom
/**
 * Evidence, redone to CLARITY: claims sit under the question their run asked (never the run's id), a ledger that could
 * not be read says so instead of "no claims yet", "Needs you" carries the unreviewed claims with a door to them, and a
 * review that is not saved says so and puts the claim back.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EvidenceClaim } from "@/lib/api";

const getRecentEvidenceClaims = vi.fn();
const listRuns = vi.fn();
const submitClaimFeedback = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getRecentEvidenceClaims: (...a: unknown[]) => getRecentEvidenceClaims(...a),
    getInvestigationsList: (...a: unknown[]) => listRuns(...a),
    submitClaimFeedback: (...a: unknown[]) => submitClaimFeedback(...a),
  };
});

const { EvidencePanel, splitClaim } = await import("@/components/EvidencePanel");

const claim = (over: Partial<EvidenceClaim>): EvidenceClaim => ({
  id: "cl_1", investigation_id: "run_a", hypothesis_id: null, claim_text: "Revenue rose: up 3% on price.",
  sql_source: "SELECT 1", metric_used: null, data_freshness: null, confidence: null,
  created_at: "2026-10-13T09:08:00Z", owner_feedback: null, feedback_note: null,
  downstream_recommendations: [], outcome_status: null, ...over,
});

const SCHEDULED = "[Scheduled-run context — written by code, not inferred]\nThis is a scheduled daily run.\n\nWhat changed in theLook in the last day? Give me the top three findings.";

beforeEach(() => {
  vi.clearAllMocks();
  listRuns.mockResolvedValue([{ id: "run_a", question: SCHEDULED }]);
  submitClaimFeedback.mockResolvedValue({});
});

describe("EvidencePanel", () => {
  it("heads a run's claims with the question it asked, never its id; an unnamed run is labelled", async () => {
    getRecentEvidenceClaims.mockResolvedValue([
      claim({ id: "a1" }), claim({ id: "b1", investigation_id: "run_b_123456789" }),
    ]);
    render(<EvidencePanel connectionId="c1" />);
    const runs = await screen.findAllByTestId("evidence-run");
    expect(runs[0].textContent).toContain("What changed in theLook in the last day?");
    expect(runs[0].textContent).not.toContain("Scheduled-run context");
    expect(runs[0].textContent).not.toContain("run_a");
    expect(runs[1].textContent).toContain("deep analysis run_b_12");
  });

  it("a ledger that could not be read says so, with Retry — never that there are no claims", async () => {
    getRecentEvidenceClaims.mockRejectedValue(new Error("the ledger answered 500"));
    render(<EvidencePanel connectionId="c1" />);
    expect(await screen.findByText(/Could not read the claim ledger/)).toBeTruthy();
    expect(screen.queryByText(/No claims yet/)).toBeNull();
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("Needs you counts the unreviewed claims, and Review narrows the list to them", async () => {
    getRecentEvidenceClaims.mockResolvedValue([
      claim({ id: "a1", claim_text: "Reviewed one: fine.", owner_feedback: "validated" }),
      claim({ id: "a2", claim_text: "Open one: still open." }),
    ]);
    render(<EvidencePanel connectionId="c1" />);
    const needs = await screen.findByTestId("evidence-needs");
    expect(needs.dataset.waiting).toBe("true");
    expect(needs.textContent).toContain("1 claim no one has reviewed");
    fireEvent.click(within(needs).getByText("Review"));
    const rows = screen.getAllByTestId("evidence-claim");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("Open one");
  });

  it("with every claim reviewed, Needs you is one muted line; a disputed claim still waits", async () => {
    getRecentEvidenceClaims.mockResolvedValue([claim({ owner_feedback: "validated" })]);
    const { unmount } = render(<EvidencePanel connectionId="c1" />);
    const quiet = await screen.findByTestId("evidence-needs");
    expect(quiet.dataset.waiting).toBe("false");
    expect(quiet.textContent).toContain("Every claim here has been reviewed.");
    unmount();
    getRecentEvidenceClaims.mockResolvedValue([claim({ owner_feedback: "disputed" })]);
    render(<EvidencePanel connectionId="c1" />);
    const needs = await screen.findByTestId("evidence-needs");
    expect(needs.dataset.waiting).toBe("true");
    expect(needs.textContent).toContain("1 claim disputed");
    expect(needs.textContent).not.toContain("no one has reviewed");
  });

  it("a review is sent with the claim's run, and one that is not saved says so and is put back", async () => {
    getRecentEvidenceClaims.mockResolvedValue([claim({ id: "a1" })]);
    submitClaimFeedback.mockRejectedValueOnce(new Error("Claim not found"));
    render(<EvidencePanel connectionId="c1" />);
    const reader = await screen.findByTestId("evidence-reader");
    fireEvent.click(within(reader).getByText("Disputed"));
    await waitFor(() => expect(submitClaimFeedback).toHaveBeenCalledWith("run_a", "a1", "disputed"));
    expect(await within(reader).findByText(/Not saved — Claim not found/)).toBeTruthy();
    expect(within(reader).getByText("Disputed").closest("button")?.getAttribute("aria-pressed")).toBe("false");
  });

  it("splits a claim at its headline", () => {
    expect(splitClaim("Revenue rose: up 3% on price.")).toEqual({ head: "Revenue rose", rest: "up 3% on price." });
    expect(splitClaim("One sentence only")).toEqual({ head: "One sentence only", rest: "" });
  });
});
