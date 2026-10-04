// @vitest-environment jsdom
/**
 * Idea 6 — the backtest, the drill and "last proven working" were API doors with no button.
 * The row says the server's proof sentence, runs a backtest on a click, and never sends a
 * test alert through the real channel without the person confirming it.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const stubs = {
  getMonitorProof: vi.fn(),
  backtestMonitor: vi.fn(),
  drillMonitor: vi.fn(),
};

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getMonitorProof: (...a: unknown[]) => stubs.getMonitorProof(...a),
    backtestMonitor: (...a: unknown[]) => stubs.backtestMonitor(...a),
    drillMonitor: (...a: unknown[]) => stubs.drillMonitor(...a),
  };
});

import { MonitorProofRow } from "./MonitorsPanel";

afterEach(() => { vi.clearAllMocks(); vi.restoreAllMocks(); });

describe("MonitorProofRow", () => {
  it("says the proof, backtests on a click, and asks before sending a test alert", async () => {
    stubs.getMonitorProof.mockResolvedValue({
      monitor_id: "m1", sentence: "never proven — no drill, no delivered alert", last_drill: null });
    stubs.backtestMonitor.mockResolvedValue({
      monitor_id: "m1", rule: "anomaly", ok: true, reason: "", sigma: 2.5, days: 365,
      series_from: "2025-10-04", series_to: "2026-10-03", firings: [],
      sentence: "Over the last 365 days this alert would have fired 41 times.", quieter_sigma: 3.5 });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<MonitorProofRow monitorId="m1" />);
    expect(await screen.findByText("never proven — no drill, no delivered alert")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Backtest" }));
    expect(await screen.findByText(
      "Over the last 365 days this alert would have fired 41 times. A quieter setting: 3.5σ.")).toBeInTheDocument();
    expect(stubs.backtestMonitor).toHaveBeenCalledWith("m1");

    fireEvent.click(screen.getByRole("button", { name: "Send test alert" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(stubs.drillMonitor).not.toHaveBeenCalled());
  });
});
