// @vitest-environment jsdom
/**
 * PX-2 — the spend screen's handoffs and its claims. What can break here is what the panel SENDS
 * (a typed cap, not a JSON blob) and what it refuses to claim: an empty cap list must say there is
 * no cap, cost with unpriced calls must read as a floor, a total with no priced call under it is not
 * a number, and an unpriced model is drawn as unknown — never as zero.
 */
import { fireEvent, render, screen, waitFor, change, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getUsageCaps = vi.fn();
const putUsageCap = vi.fn();
const deleteUsageCap = vi.fn();
const getUsageReport = vi.fn();
const getUsageSummary = vi.fn();
const getRouteMix = vi.fn();
const getAuditFeed = vi.fn();
const getCostSql = vi.fn();
const getConnections = vi.fn();

// Every read the panel makes is mocked: an unmocked one would reach the live API from jsdom.
vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getUsageCaps: (...a: unknown[]) => getUsageCaps(...a),
    putUsageCap: (...a: unknown[]) => putUsageCap(...a),
    deleteUsageCap: (...a: unknown[]) => deleteUsageCap(...a),
    getUsageReport: (...a: unknown[]) => getUsageReport(...a),
    getUsageSummary: (...a: unknown[]) => getUsageSummary(...a),
    getRouteMix: (...a: unknown[]) => getRouteMix(...a),
    getAuditFeed: (...a: unknown[]) => getAuditFeed(...a),
    getCostSql: (...a: unknown[]) => getCostSql(...a),
    getConnections: (...a: unknown[]) => getConnections(...a),
  };
});

const { SpendPanel } = await import("@/components/SpendPanel");

const row = (over: Record<string, unknown>) => ({
  provider: "openrouter", model: "m1", calls: 10, failures: 0, prompt_tokens: 1, completion_tokens: 1,
  total_tokens: 1200, calls_without_usage: 0, unpriced_calls: 0, cost_usd: 0, cost_is_complete: true,
  mean_ms: 100, failure_rate: 0, ...over,
});
const usage = (rows: Record<string, unknown>[]) => ({
  axes: ["provider", "model"], total_calls: rows.reduce((n, r) => n + Number(r.calls), 0), rows, unattributed: {},
});

beforeEach(() => {
  vi.clearAllMocks();
  getUsageCaps.mockResolvedValue({ caps: [], scopes: ["org", "user"],
    metrics: ["calls", "total_tokens", "cost_usd"], actions: ["alert", "block"] });
  putUsageCap.mockResolvedValue({});
  getUsageReport.mockResolvedValue(usage([
    row({ model: "m1", calls: 10, unpriced_calls: 4, cost_usd: 1.5, cost_is_complete: false }),
  ]));
  getUsageSummary.mockImplementation(async (p?: { range?: string }) => ({
    calls: p?.range === "7d" ? 614 : 3, tokens: 9000, calls_without_usage: 0,
    sites: [{ caller: "aughor.sql.writer:fix", calls: 2, total_tokens: 6000, prompt_tokens: 0, calls_without_usage: 0 }],
  }));
  getRouteMix.mockResolvedValue({ converse_share: null });
  getAuditFeed.mockResolvedValue({ categories: ["governance_change"], category: null, count: 0, events: [] });
  getCostSql.mockResolvedValue({ sql: "SELECT 1", table: "session_events", kind: "llm_call" });
  getConnections.mockResolvedValue([{ id: "914df862", name: "LuxExperience" }]);
});

describe("SpendPanel", () => {
  // These assert the CLAIM, not the layout: what must never change is that an uncapped org is told
  // so, and that an incomplete cost is never shown as a total.
  it("the figures row leads with spend, calls, failures and the cap", async () => {
    getUsageReport.mockResolvedValue(usage([
      row({ provider: "gemini", model: "gemini-3.1-flash-lite", calls: 1326, failures: 18, unpriced_calls: 1308, cost_is_complete: false }),
      row({ model: "deepseek/deepseek-v4.1-flash", calls: 514, failures: 13, cost_usd: 1.765142 }),
    ]));
    render(<SpendPanel />);
    const figures = await screen.findByTestId("spend-figures");
    await waitFor(() => expect(within(figures).getByTestId("spend-calls").textContent).toMatch(/614 in the last 7 days/));
    expect(within(figures).getByTestId("spend-spent").textContent).toBe("Spent · at least$1.7729% of calls priced");
    expect(within(figures).getByTestId("spend-calls").textContent).toMatch(/^Model calls1,840/);
    expect(within(figures).getByTestId("spend-failed").textContent).toBe("Failed311.7% · most on gemini-3.1-flash-lite");
    expect(within(figures).getByTestId("spend-cap").textContent).toBe("Spend capNonenothing stops a runaway run");
  });

  it("an empty cap list says there is no cap, never nothing — and offers to set one", async () => {
    render(<SpendPanel />);
    await waitFor(() => expect(screen.getByTestId("spend-cap").textContent).toMatch(/None/));
    expect(screen.getByTestId("spend-cap").textContent).toMatch(/nothing stops a runaway run/);
    expect(within(screen.getByTestId("spend-needs")).getByRole("button", { name: "Set a cap" })).toBeTruthy();
  });

  it("declaring a cap hands the endpoint a typed body", async () => {
    render(<SpendPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Set a cap" }));
    change(await screen.findByTestId("cap-limit"), { target: { value: "25" } });
    fireEvent.click(screen.getByTestId("cap-declare"));
    await waitFor(() => expect(putUsageCap).toHaveBeenCalledTimes(1));
    expect(putUsageCap.mock.calls[0][0]).toEqual({
      scope: "org", subject: "*", metric: "cost_usd", limit: 25,
      window_hours: 24, action: "alert",
    });
  });

  it("cost with unpriced calls reads as a floor, not a total", async () => {
    render(<SpendPanel />);
    const spent = await screen.findByTestId("spend-spent");
    await waitFor(() => expect(spent.textContent).toMatch(/\$1\.50/));
    // Both halves matter: "at least" on the figure, and the share priced beside it.
    expect(spent.textContent).toMatch(/at least/);
    expect(spent.textContent).toMatch(/60% of calls priced/);
    expect(screen.getByTestId("spend-needs").textContent).toMatch(/4 calls have no price, so the real spend is unknown/);
  });

  it("an unpriced model is drawn unknown — hatched, and the legend says 'no price'", async () => {
    getUsageReport.mockResolvedValue(usage([
      row({ provider: "gemini", model: "gemini-3.1-flash-lite", calls: 20, total_tokens: 4000, unpriced_calls: 20, cost_is_complete: false }),
      row({ model: "nvidia/nemotron:free", calls: 8, total_tokens: 900 }),
    ]));
    render(<SpendPanel />);
    const models = await screen.findByTestId("spend-models");
    await waitFor(() => expect(models.textContent).toMatch(/gemini-3\.1-flash-lite/));
    const unknown = models.querySelectorAll('[data-unknown="true"]');
    expect(unknown).toHaveLength(1);
    expect(unknown[0].closest("span")?.getAttribute("title")).toMatch(/20 calls with no price/);
    expect(models.textContent).toMatch(/no price/);
    expect(models.textContent).toMatch(/openrouter · 8 calls · free/);
  });

  it("a total with no priced call under it is unknown, never $0.00", async () => {
    getUsageReport.mockResolvedValue(usage([row({ calls: 7, unpriced_calls: 7, cost_is_complete: false })]));
    render(<SpendPanel />);
    const spent = await screen.findByTestId("spend-spent");
    await waitFor(() => expect(spent.textContent).toMatch(/Unknown/));
    expect(spent.textContent).toMatch(/no call priced/);
    expect(spent.textContent).not.toMatch(/\$0\.00/);
  });

  it("governance is said once per kind, and View opens exactly the events behind a row", async () => {
    const q = (verdict: string, hypothesis_id: string, at: string) => ({ category: "data_access", kind: "query.execution", at,
      actor: "default", org_id: "default", conn_id: "8233e4fd", summary: `query ${verdict}`, detail: { verdict, hypothesis_id } });
    getAuditFeed.mockResolvedValue({ categories: ["data_access", "action_decision"], category: null, count: 4, events: [
      q("safe", "__monitor__", "2026-10-10T12:19:35Z"),
      q("suspicious", "__brief_period__", "2026-10-10T12:00:00Z"),
      { category: "action_decision", kind: "action.approval", at: "2026-10-10T11:35:10Z", actor: "amit", org_id: "default",
        conn_id: "914df862", summary: "criterion_failed x.resolve_case on 914df862",
        detail: { decision: "criterion_failed", action: "x.resolve_case" } },
      q("safe", "objects.list", "2026-10-10T10:45:45Z"),
    ] });
    render(<SpendPanel />);
    const gov = await screen.findByTestId("spend-governance");
    await waitFor(() => expect(within(gov).getAllByTestId("governance-fold")).toHaveLength(2));
    const [failed, checks] = within(gov).getAllByTestId("governance-fold");
    expect(failed.textContent).toMatch(/An action's check failed.*resolve case · LuxExperience/);
    expect(checks.textContent).toMatch(/Query checks2 safe · 1 flagged were the platform's own reads3/);
    expect(within(checks).queryByRole("button", { name: "View" })).toBeNull();

    fireEvent.click(within(failed).getByRole("button", { name: "View" }));
    const shown = await within(gov).findAllByTestId("governance-feed-row");
    expect(shown).toHaveLength(1);
    expect(shown[0].textContent).toMatch(/criterion_failed x\.resolve_case/);
    expect(within(gov).getByTestId("feed-count").textContent).toBe("1 of 4 events");
    fireEvent.click(within(gov).getByRole("button", { name: "Show all" }));
    expect(within(gov).getAllByTestId("governance-feed-row")).toHaveLength(4);
  });
});
