// @vitest-environment jsdom
/**
 * The rail's amber alert badge counts what waits on a person: an alert not acknowledged — and, since TC-4, not closed
 * by a recovery. A recovery itself waits on nobody.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MonitorAlert } from "@/lib/api";

const api = vi.hoisted(() => ({
  getAllAlerts: vi.fn(),
  getDepartureSummary: vi.fn(async () => ({ awaiting: 0 })),
  getDepartures: vi.fn(async () => []),
}));
vi.mock("@/lib/api", async importOriginal => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));
vi.mock("@/lib/record", () => ({
  WAITING_CHANGED_EVENT: "aughor:waiting-changed",
  getSetAside: vi.fn(async () => ({ active: [] })),
  listDecisions: vi.fn(async () => []),
  listInquiries: vi.fn(async () => []),
}));
vi.mock("@/lib/events", () => ({ subscribeKernelEvents: vi.fn(() => () => {}) }));

import { useNavCounts } from "./useNavCounts";

const alert = (over: Partial<MonitorAlert>): MonitorAlert => ({
  id: "a", monitor_id: "m1", monitor_name: "Units", conn_id: "c1", metric_name: null, triggered_at: "2026-10-25T09:00:00Z",
  alert_on: "threshold_cross", severity: "warning", current_value: 5, previous_value: null, threshold: 10, message: "x",
  caveat: null, acknowledged: false, acknowledged_at: null, ...over,
});

afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); });

describe("useNavCounts", () => {
  it("counts the open alerts — never a recovery, nor an alert one closed", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [] })));
    api.getAllAlerts.mockResolvedValue([
      alert({ id: "open" }),
      alert({ id: "closed", closed_by: "r1", closed_at: "2026-10-25T10:00:00Z" }),
      alert({ id: "r1", alert_on: "recovered", severity: "info", closes: "closed" }),
      alert({ id: "seen", acknowledged: true }),
    ]);
    const { result } = renderHook(() => useNavCounts("w1"));
    await waitFor(() => expect(api.getAllAlerts).toHaveBeenCalled());
    await waitFor(() => expect(result.current.unackedAlerts).toBe(1));
  });
});
