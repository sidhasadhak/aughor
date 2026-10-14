// @vitest-environment jsdom
/**
 * The trace list says a read that failed — it drew "Recording is on — the next question asked will appear here as a
 * trace" over a list it never read (2026-10-13). Every API call is stubbed: nothing reaches the live API.
 */
import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/lib/testing";

const api = vi.hoisted(() => ({
  getTraces: vi.fn(),
  getVerdicts: vi.fn(async () => []),
  getTrace: vi.fn(),
  getTraceLogs: vi.fn(),
  getTraceFeedback: vi.fn(),
}));
vi.mock("@/lib/api", async importOriginal => ({ ...(await importOriginal<Record<string, unknown>>()), ...api }));

const { TraceExplorerPanel } = await import("@/components/TraceExplorerPanel");

describe("the trace list", () => {
  it("says a list it could not read, with a retry — never 'Recording is on'", async () => {
    api.getTraces.mockReset()
      .mockRejectedValueOnce(new Error("Reading the traces failed (503)"))
      .mockResolvedValue({ traces: [], total: 0, scanned_events: 0 });
    render(<TraceExplorerPanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Reading the traces failed (503)");
    expect(screen.queryByText(/Recording is on/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText(/Recording is on/)).toBeInTheDocument();
  });
});
