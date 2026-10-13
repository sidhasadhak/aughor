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
const getLearningDataset = vi.fn();

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
    getLearningDataset: (...a: unknown[]) => getLearningDataset(...a),
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

describe("MemoryPanel reads that fail, and the corpus", () => {
  it("trusted queries that could not be read say so — never that there are none", async () => {
    listTrustedQueries.mockRejectedValue(new Error("Failed to fetch trusted queries (500)"));
    render(<MemoryPanel />);
    expect((await screen.findAllByText(/Could not read the trusted queries/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/None yet/)).toBeNull();
  });

  it("a training corpus that could not be read says so instead of vanishing", async () => {
    listTrustedQueries.mockResolvedValue([]);
    render(<MemoryPanel />);
    expect(await screen.findByText(/Could not read the training corpus/)).toBeTruthy();
  });

  it("inspecting a corpus asks for the dataset it is exported as, and a gate that is no dataset offers none", async () => {
    listTrustedQueries.mockResolvedValue([]);
    getLearningDatasets.mockResolvedValue({
      stats: { sft: { datasets: 1, examples: 0 } },
      gates: { sft: { have: 0, need: 1000, passes: false }, guard_days: { have: 39, need: 30, passes: true } },
    });
    getLearningDataset.mockResolvedValue({ found: true, dataset: { name: "nl2sql-sft", version: 1, row_count: 0 }, lineage: [] });
    render(<MemoryPanel />);
    const corpus = await screen.findByTestId("memory-corpus");
    await waitFor(() => expect(corpus.textContent).toContain("39 of 30 days"));
    const inspect = corpus.querySelectorAll("button");
    const names = [...inspect].map(b => b.textContent);
    expect(names).toContain("sft");
    expect(names).not.toContain("guard days");
    fireEvent.click([...inspect].find(b => b.textContent === "sft")!);
    await waitFor(() => expect(getLearningDataset).toHaveBeenCalledWith("nl2sql-sft"));
  });
});
