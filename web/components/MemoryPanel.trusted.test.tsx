// @vitest-environment jsdom
/**
 * PX-4 — the trusted-query write half's handoffs: a proposed row offers Approve and
 * the transition carries the action + actor; a draft that failed verification says
 * so and offers re-verification rather than approval.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TrustedQueryRow } from "@/lib/api";

const listTrustedQueries = vi.fn();
const transitionTrustedQuery = vi.fn();
const getLearningSummary = vi.fn();
const getLearningDatasets = vi.fn();
const listRememberedReadings = vi.fn();
const getConnections = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    listTrustedQueries: (...a: unknown[]) => listTrustedQueries(...a),
    transitionTrustedQuery: (...a: unknown[]) => transitionTrustedQuery(...a),
    getLearningSummary: (...a: unknown[]) => getLearningSummary(...a),
    getLearningDatasets: (...a: unknown[]) => getLearningDatasets(...a),
    listRememberedReadings: (...a: unknown[]) => listRememberedReadings(...a),
    getConnections: (...a: unknown[]) => getConnections(...a),
    createTrustedQuery: vi.fn(),
    editTrustedQuery: vi.fn(),
    deleteTrustedQuery: vi.fn(),
    getLearningDataset: vi.fn(),
    revokeRememberedReading: vi.fn(),
    runLearningExport: vi.fn(),
  };
});

const { MemoryPanel } = await import("@/components/MemoryPanel");

const row = (over: Partial<TrustedQueryRow>): TrustedQueryRow => ({
  id: "tq_1", connection_id: "c1", question: "Revenue by region?",
  sql: "SELECT 1", tables: [], note: "", tags: [], status: "proposed",
  version: 1, verification: null, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  getLearningSummary.mockResolvedValue({
    ledger: { resolutions: 0, served_total: 0, by_source: {} },
    verdicts: { total: 0, acceptance_rate: null, trend: [] },
    trusted: { queries: 1 },
  });
  getLearningDatasets.mockResolvedValue(null);
  listRememberedReadings.mockResolvedValue([]);
  getConnections.mockResolvedValue([]);
  transitionTrustedQuery.mockResolvedValue({ trusted_query: {}, audit: {} });
});

describe("MemoryPanel trusted governance", () => {
  it("approving a proposed row hands the transition the action and an actor", async () => {
    listTrustedQueries.mockResolvedValue([row({ status: "proposed" })]);
    render(<MemoryPanel />);
    fireEvent.click(await screen.findByTestId("tq-approve-tq_1"));
    await waitFor(() => expect(transitionTrustedQuery).toHaveBeenCalledTimes(1));
    const [id, action, actor] = transitionTrustedQuery.mock.calls[0];
    expect(id).toBe("tq_1");
    expect(action).toBe("approve");
    expect(typeof actor).toBe("string");
    expect((actor as string).length).toBeGreaterThan(0);
  });

  it("a failed-verification draft says it stays out of prompts and never offers Approve", async () => {
    listTrustedQueries.mockResolvedValue([
      row({ id: "tq_2", status: "draft", verification: { passed: false } }),
    ]);
    render(<MemoryPanel />);
    expect(await screen.findByText(/stays a draft, out of every prompt/)).toBeTruthy();
    expect(screen.queryByTestId("tq-approve-tq_2")).toBeNull();
    expect(screen.getByText(/Re-verify & propose/)).toBeTruthy();
  });
});
