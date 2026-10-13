// @vitest-environment jsdom
/**
 * Intelligence › Profile, redone to CLARITY (2026-10-13): a page of prose and facts beside a column of domains. What
 * these hold is what the redo added — a read that fails says so with Retry instead of reading as an empty section, and
 * a status column whose values run long (one explorer run mapped a megabyte JSON payload as a status) shows its first
 * values, cut, and counts the rest.
 */
import { fireEvent, render, screen, waitFor } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBusinessProfile, getDomainInsights, getPatterns, getSchemaProfile,
  type BusinessProfileResponse, type ExplorationFindings, type LifecycleMap,
} from "@/lib/api";
import { STATES_SHOWN, statusValues } from "@/components/ProfilePanel";

vi.mock("@/components/BriefingPanel", () => ({ EvidenceDrawer: () => null, FindingActions: () => null }));

const PROFILE: BusinessProfileResponse = {
  available: true, generated_at: "2026-09-23T15:27:19Z",
  profile: { industry: "DTC Apparel", business_model: "Transactional retail", summary: "An online apparel retailer.",
    north_star_metrics: [], key_questions: [], confidence: 0.78, currency_code: "USD", evidence: "Orders and order items." },
};
const DOMAINS = {
  Catalog: { queries_used: 6, budget_cap: 15, angles_covered: ["mix"], insights: [
    { id: "f1", domain: "Catalog", angle: "mix", entities_involved: [], dimensions: [], measures: [], finding: "Jeans lead revenue.",
      sql: "", confidence: 0.9, novelty: 6, generated_at: "2026-10-08T00:00:00Z" },
    { id: "f2", domain: "Catalog", angle: "mix", entities_involved: [], dimensions: [], measures: [], finding: "Socks trail.",
      sql: "", confidence: 0.7, novelty: 2, generated_at: "2026-10-08T00:00:00Z" },
  ] },
};
const FINDINGS: ExplorationFindings = {
  connection_id: "c1", phase: "complete", null_meanings: {}, join_verifications: [], distributions: {}, insights: [],
  lifecycle_maps: { orders: { status_column: "status", states: ["Shipped", "Returned"], terminal_states: ["Returned"], active_states: [], transitions: [] } },
};

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getActionTriggers: vi.fn(async () => []),
  getDomainInsights: vi.fn(async () => DOMAINS),
  getOrgIntelligence: vi.fn(async () => []),
  getPatterns: vi.fn(async () => ({ patterns: [], count: 0 })),
  getCanvasPatterns: vi.fn(async () => ({ patterns: [], count: 0 })),
  getBusinessProfile: vi.fn(async () => PROFILE),
  getEffectiveSettings: vi.fn(async () => ({ industry: "", currency_code: "", fiscal_year_start_month: 1 })),
  getSchemaProfile: vi.fn(async () => ({ available: true, columns: [], tables: [
    { table: "orders", row_count: 125080, grain_column: "order_id", grain_verified: true, primary_timestamp: "created_at",
      date_range: ["2019-01-01", "2026-10-12"], freshness_lag_hours: null, computed_at: "2026-10-11T10:00:00Z" },
  ] })),
  getMetrics: vi.fn(async () => []),
  getExplorationFindings: vi.fn(async () => FINDINGS),
}));

beforeEach(() => vi.clearAllMocks());

describe("statusValues", () => {
  it("shows a status column's first values, cuts a long one, and counts the rest", () => {
    const payload = `{"ids":${"x".repeat(5000)}}`;
    const lc: LifecycleMap = { status_column: "payload", states: [payload, ...Array.from({ length: 11 }, (_, i) => `s${i}`)],
      terminal_states: ["s0"], active_states: [], transitions: [] };
    const { shown, more } = statusValues(lc);
    expect(shown).toHaveLength(STATES_SHOWN);
    expect(more).toBe(12 - STATES_SHOWN);
    expect(shown[0].text.length).toBeLessThanOrEqual(40);
    expect(shown[0].full.length).toBeLessThanOrEqual(201);
    expect(shown[1]).toMatchObject({ text: "s0", terminal: true });
  });
});

describe("ProfileLayer", () => {
  it("opens on the business in prose and its tables, with no figure row and no Needs you", async () => {
    const { ProfileLayer } = await import("@/components/ProfileLayer");
    render(<ProfileLayer connectionId="c1" />);
    await screen.findByText("An online apparel retailer.");
    expect(screen.getByRole("heading", { name: "DTC Apparel" })).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("profile-tables").textContent).toContain("125,080"));
    expect(screen.queryByLabelText("Needs you")).toBeNull();
    // Why Aughor thinks so is one click away, not a paragraph on the page.
    expect(screen.queryByText("Orders and order items.")).toBeNull();
    fireEvent.click(screen.getByTestId("profile-why"));
    expect(screen.getByText("Orders and order items.")).toBeTruthy();
  });

  it("says a failed section read and reads it again on Retry, never as an empty section", async () => {
    vi.mocked(getSchemaProfile).mockRejectedValueOnce(new Error("Failed to fetch schema profile"));
    vi.mocked(getBusinessProfile).mockRejectedValueOnce(new Error("network down"));
    const { ProfileLayer } = await import("@/components/ProfileLayer");
    render(<ProfileLayer connectionId="c1" />);
    await waitFor(() => expect(screen.getByTestId("profile-tables").textContent).toContain("Could not read the table profile"));
    expect(screen.getByTestId("profile-tables").textContent).not.toContain("No table profile yet");
    expect(await screen.findByText(/Could not read the business profile/)).toBeTruthy();
    const retries = screen.getAllByRole("button", { name: "Retry" });
    retries.forEach(b => fireEvent.click(b));
    await waitFor(() => expect(screen.getByTestId("profile-tables").textContent).toContain("125,080"));
    expect(await screen.findByText("An online apparel retailer.")).toBeTruthy();
  });

  it("lists the domains as a column, and a failed read of them is said, not shown as no domains", async () => {
    vi.mocked(getDomainInsights).mockRejectedValueOnce(new Error("Failed to fetch the domains"));
    const { ProfileLayer } = await import("@/components/ProfileLayer");
    render(<ProfileLayer connectionId="c1" />);
    await waitFor(() => expect(screen.getByRole("navigation").textContent).toContain("Could not read the domains"));
    expect(screen.getByRole("navigation").textContent).not.toContain("No domains yet");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("navigation").textContent).toContain("Catalog"));
  });

  it("opens a domain on its findings grouped by novelty, and says a failed read of its patterns", async () => {
    vi.mocked(getPatterns).mockRejectedValueOnce(new Error("Failed to fetch patterns"));
    const { ProfileLayer } = await import("@/components/ProfileLayer");
    render(<ProfileLayer connectionId="c1" />);
    fireEvent.click(await screen.findByRole("button", { name: /^Catalog/ }));
    const findings = await screen.findByTestId("domain-findings");
    expect(screen.getByTestId("findings-high").textContent).toContain("Jeans lead revenue.");
    expect(screen.getByTestId("findings-low").textContent).toContain("Socks trail.");
    expect(findings.textContent).not.toContain("Mid novelty");
    fireEvent.mouseDown(screen.getByRole("tab", { name: /Patterns/ }));
    fireEvent.click(screen.getByRole("tab", { name: /Patterns/ }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Could not read the patterns"));
    expect(screen.queryByText(/No patterns yet/)).toBeNull();
  });
});
