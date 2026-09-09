// @vitest-environment jsdom
/**
 * PX-2 — the spend cockpit's handoffs. What can break here is what the panel SENDS
 * (a typed cap, not a JSON blob) and what it refuses to claim (an empty cap list must
 * say "uncapped", cost with unpriced calls must read as a floor).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getUsageCaps = vi.fn();
const putUsageCap = vi.fn();
const deleteUsageCap = vi.fn();
const getUsageReport = vi.fn();
const getModelUsage = vi.fn();
const getRouteMix = vi.fn();
const getAuditFeed = vi.fn();
const getCostSql = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getUsageCaps: (...a: unknown[]) => getUsageCaps(...a),
    putUsageCap: (...a: unknown[]) => putUsageCap(...a),
    deleteUsageCap: (...a: unknown[]) => deleteUsageCap(...a),
    getUsageReport: (...a: unknown[]) => getUsageReport(...a),
    getModelUsage: (...a: unknown[]) => getModelUsage(...a),
    getRouteMix: (...a: unknown[]) => getRouteMix(...a),
    getAuditFeed: (...a: unknown[]) => getAuditFeed(...a),
    getCostSql: (...a: unknown[]) => getCostSql(...a),
  };
});

const { SpendPanel } = await import("@/components/SpendPanel");

beforeEach(() => {
  vi.clearAllMocks();
  getUsageCaps.mockResolvedValue({ caps: [], scopes: ["org", "user"],
    metrics: ["calls", "total_tokens", "cost_usd"], actions: ["alert", "block"] });
  putUsageCap.mockResolvedValue({});
  getUsageReport.mockResolvedValue({ axes: ["provider", "model"], total_calls: 10,
    rows: [{ provider: "openrouter", model: "m1", calls: 10, failures: 0,
      prompt_tokens: 1, completion_tokens: 1, total_tokens: 1200,
      calls_without_usage: 0, unpriced_calls: 4, cost_usd: 1.5,
      cost_is_complete: false, mean_ms: 100, failure_rate: 0 }],
    unattributed: {} });
  getModelUsage.mockResolvedValue({ models: [] });
  getRouteMix.mockResolvedValue({ converse_share: null });
  getAuditFeed.mockResolvedValue({ categories: ["governance_change"], category: null, count: 0, events: [] });
  getCostSql.mockResolvedValue({ sql: "SELECT 1", table: "session_events", kind: "llm_call" });
});

describe("SpendPanel", () => {
  it("an empty cap list says 'uncapped', never nothing", async () => {
    render(<SpendPanel />);
    expect(await screen.findByText(/every model call is currently uncapped/)).toBeTruthy();
  });

  it("declaring a cap hands the endpoint a typed body", async () => {
    render(<SpendPanel />);
    fireEvent.change(await screen.findByTestId("cap-limit"), { target: { value: "25" } });
    fireEvent.click(screen.getByTestId("cap-declare"));
    await waitFor(() => expect(putUsageCap).toHaveBeenCalledTimes(1));
    expect(putUsageCap.mock.calls[0][0]).toEqual({
      scope: "org", subject: "*", metric: "cost_usd", limit: 25,
      window_hours: 24, action: "alert",
    });
  });

  it("cost with unpriced calls reads as a floor, not a total", async () => {
    render(<SpendPanel />);
    expect(await screen.findByText(/a floor, not a total/)).toBeTruthy();
    expect(screen.getByText(/≥ \$1\.50/)).toBeTruthy();
  });
});
