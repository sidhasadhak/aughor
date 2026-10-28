// @vitest-environment jsdom
/**
 * Settings ▸ Organization, redone to CLARITY (2026-10-12). Pinned: the figures row says what is in force — the
 * industries read, this quarter's priorities, the owners the platform can reach, the Explorer's budget — and "Needs
 * you" holds an owner nobody can reach, folded into one row with the button that takes a person to its Link box. A
 * link made in the owners' panel is announced, and the count follows it. An owners read that fails is said, never
 * taken for "nobody is unresolved". The one Save still writes the settings the form holds.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IndustryChoice, OrgSettings, OwnerEntry } from "@/lib/api";

const api = vi.hoisted(() => ({
  getOrgSettings: vi.fn(), getWorkspace: vi.fn(), getCapabilities: vi.fn(), getEffectiveSettings: vi.fn(),
  updateOrgSettings: vi.fn(), updateWorkspace: vi.fn(), listOwners: vi.fn(), linkOwner: vi.fn(), unlinkOwner: vi.fn(),
  getIndustryChoice: vi.fn(), updateIndustryChoice: vi.fn(), getAgentPolicy: vi.fn(), updateAgentPolicy: vi.fn(),
  clearAgentPolicy: vi.fn(), getMyAccess: vi.fn(), getOrgLLM: vi.fn(), getOrgAllows: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { OrgSettingsPanel } from "./OrgSettingsPanel";
import { OWNERS_CHANGED } from "./OwnersPanel";

const SETTINGS: OrgSettings = {
  company_name: "", website: "", hq_location: "", industry: "", currency_code: "USD", timezone: "", date_format: "",
  fiscal_year_start_month: 1, chart_palette: "", chat_first_home: false, exploration_monthly_tokens: 0,
  priorities: [
    { metric: "return rate", target: "< 8%", direction: "down", by: "Q4", note: "" },
    { metric: "AOV", target: "$90", direction: "up", by: "Q4", note: "" },
  ],
};
const CHOICE: IndustryChoice = {
  industries: ["retail"], source: "settings", updated_at: "", ignored: [], problem: "", profiles_refreshed: 0,
  shipped: [
    { id: "airline", name: "Airline", title: "", description: "" },
    { id: "retail", name: "Retail and e-commerce", title: "", description: "" },
    { id: "saas", name: "SaaS", title: "", description: "" },
  ],
};
const unresolved: OwnerEntry = { owner_text: "Revenue team", owner_key: "revenue team",
  uses: [{ kind: "metric", id: "revenue", connection_id: "" }, { kind: "metric", id: "aov", connection_id: "" }],
  principal: null, resolved: false, how: "unresolved", linked_by: "", linked_at: "" };
const reachable: OwnerEntry = { owner_text: "group:finance", owner_key: "group:finance",
  uses: [{ kind: "metric", id: "margin", connection_id: "" }], principal: "group:finance", resolved: true,
  how: "principal", linked_by: "", linked_at: "" };

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getOrgSettings.mockResolvedValue(SETTINGS);
  api.getCapabilities.mockResolvedValue({ multi_tenant: false });
  api.getEffectiveSettings.mockResolvedValue(SETTINGS);
  api.updateOrgSettings.mockImplementation(async (s: OrgSettings) => s);
  api.listOwners.mockResolvedValue({ owners: [unresolved, reachable], links: [] });
  api.getIndustryChoice.mockResolvedValue(CHOICE);
  api.getAgentPolicy.mockResolvedValue({
    effective: { level: "run", connections: null, tools: null, set_by: "", updated_at: "", source: "default", narrowed_by: [] },
    saved: null, environment: { level: null, connections: null, tools: null }, levels: ["read", "run", "act"],
  });
  api.getMyAccess.mockResolvedValue(null);
  const off = { allowed: false, set: false };
  api.getOrgAllows.mockResolvedValue({ share_aggregates: off, outside_row_model: off, reason_to_read_runs: off,
                                       scheduled_model_work: off });
  // The playbook's count is read with a bare fetch; this test is about the figures, so it answers nothing.
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => [] })));
});

const value = (id: string) => screen.getByTestId(`${id}-value`);

describe("Settings ▸ Organization", () => {
  it("opens on four figures: the industries read, the priorities, the owners reachable, the budget", async () => {
    render(<OrgSettingsPanel />);
    await waitFor(() => expect(value("fig-industries")).toHaveTextContent("1 of 3"));
    expect(screen.getByTestId("fig-industries")).toHaveTextContent("Retail and e-commerce");
    expect(value("fig-priorities")).toHaveTextContent("2");
    expect(screen.getByTestId("fig-priorities")).toHaveTextContent("return rate · AOV");
    await waitFor(() => expect(value("fig-owners")).toHaveTextContent("1 of 2"));
    expect(screen.getByTestId("fig-owners")).toHaveTextContent("1 unresolved");
    expect(value("fig-budget")).toHaveTextContent("None");
    expect(screen.getByTestId("fig-budget")).toHaveTextContent("no monthly cap");
  });

  it("puts an owner nobody can reach under Needs you, with the button that goes to its Link box", async () => {
    render(<OrgSettingsPanel />);
    const row = await screen.findByTestId("needs-owners");
    expect(screen.getByTestId("org-needs")).toHaveAttribute("data-waiting", "true");
    expect(row).toHaveTextContent("1 owner is unresolved");
    expect(row).toHaveTextContent("Revenue team · 2 metrics");
    expect(within(row).getByRole("button", { name: "Link" })).toBeInTheDocument();
  });

  it("says nothing needs you when every owner is reachable, and follows a link made in the owners' panel", async () => {
    render(<OrgSettingsPanel />);
    await screen.findByTestId("needs-owners");
    api.listOwners.mockResolvedValue({ owners: [{ ...unresolved, resolved: true, how: "linked", principal: "user:ana@corp" }, reachable], links: [] });
    await act(async () => { window.dispatchEvent(new Event(OWNERS_CHANGED)); });
    await waitFor(() => expect(screen.queryByTestId("needs-owners")).toBeNull());
    expect(screen.getByTestId("org-needs")).toHaveAttribute("data-waiting", "false");
    expect(screen.getByTestId("org-needs")).toHaveTextContent("Nothing needs you · every owner the declarations name is reachable");
    expect(value("fig-owners")).toHaveTextContent("2 of 2");
  });

  it("says the owners could not be read, rather than that nobody is unresolved", async () => {
    api.listOwners.mockRejectedValue(new Error("listOwners failed: 500"));
    render(<OrgSettingsPanel />);
    await waitFor(() => expect(screen.getByTestId("fig-owners")).toHaveTextContent("could not be read"));
    expect(screen.getByTestId("org-needs")).toHaveTextContent("the owners could not be read");
  });

  it("marks an edit unsaved, and the one Save writes the settings the form holds", async () => {
    render(<OrgSettingsPanel />);
    const name = await screen.findByLabelText("Company name");
    fireEvent.change(name, { target: { value: "theLook" } });
    expect(screen.getByTestId("org-save")).toHaveTextContent("unsaved changes");
    fireEvent.click(within(screen.getByTestId("org-save")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updateOrgSettings).toHaveBeenCalledWith({ ...SETTINGS, company_name: "theLook" }));
  });

  // ROADMAP §3.65 — the four choices an organisation makes, off unless chosen; one the server's environment turns on
  // while nobody has chosen says so, rather than looking off.
  it("shows what Aughor may do, says which one is on only through the environment, and saves a choice", async () => {
    const off = { allowed: false, set: false };
    api.getOrgAllows.mockResolvedValue({ share_aggregates: off, reason_to_read_runs: off, scheduled_model_work: off,
                                         outside_row_model: { allowed: true, set: false } });
    render(<OrgSettingsPanel />);
    const card = await screen.findByTestId("org-allows");
    await waitFor(() => expect(screen.getByTestId("org-allows-outside_row_model")).toHaveAttribute("data-on", "true"));
    expect(screen.getByTestId("org-allows-outside_row_model-from-server")).toHaveTextContent(
      "On through this server's environment until you choose here.");
    for (const k of ["share_aggregates", "reason_to_read_runs", "scheduled_model_work"]) {
      expect(screen.getByTestId(`org-allows-${k}`)).toHaveAttribute("data-on", "false");
      expect(screen.queryByTestId(`org-allows-${k}-from-server`)).toBeNull();
    }
    fireEvent.click(within(card).getByRole("checkbox", { name: "Share summary statistics with other installs" }));
    expect(screen.getByTestId("org-allows-share_aggregates")).toHaveAttribute("data-on", "true");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updateOrgSettings).toHaveBeenCalledWith(expect.objectContaining({ share_aggregates: true })));
  });
});
