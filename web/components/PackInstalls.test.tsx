// @vitest-environment jsdom
/**
 * Where a pack is installed and what upgrading it brings (Arc FA, FA-6, flag `packs.installed_versions`). The API is
 * stood in for; what is asserted is what the row says of its version, how the diff marks what a person declined, and
 * that the upgrade is asked for the connection the row names.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getPackInstalls: vi.fn(), getPackUpgrade: vi.fn(), upgradePack: vi.fn(), getConnections: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const toasts = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/components/ui/toast", async (original) => ({ ...(await original<typeof import("@/components/ui/toast")>()), toast: toasts }));

import { PackInstalls, declinedMark, versionLine } from "@/components/PackInstalls";
import type { PackOfferedItem, PackUpgradeDiff } from "@/lib/api";

const item = (over: Partial<PackOfferedItem>): PackOfferedItem => ({
  key: "k", kind: "term", label: "\"nim\"", said: "", was: "", declined: false, declined_in: null, will_offer: true, why: "", ...over,
});

const DIFF: PackUpgradeDiff = {
  pack: "banking", connection_id: "c1", schema: "bank", installed: 1, available: 2, recorded: true,
  bound_by: "user:ana", bound_at: "2026-10-26T10:00:00Z", upgrade_available: true, will_offer: 2, not_read: {},
  added: [item({ key: "term:a", label: "\"earning asset margin\"", said: "metric net_interest_margin" })],
  changed: [item({ key: "alert:b", kind: "alert", label: "Net interest margin below its prior range", was: "fires below 0.02",
                   said: "fires below 0.025", declined: true, declined_in: 1, why: "declined before, and changed since — offered again" })],
  removed: [item({ key: "term:c", label: "\"margin on earning assets\"", will_offer: false, why: "no longer in the pack" })],
  kept_declined: [item({ key: "term:d", label: "\"nim\"", declined: true, declined_in: 1, will_offer: false,
                         why: "declined, and unchanged since — not offered again" })],
};

beforeEach(() => {
  for (const f of Object.values(api)) f.mockReset();
  toasts.success.mockReset(); toasts.error.mockReset();
  api.getConnections.mockResolvedValue([{ id: "c1", name: "Lending warehouse" }]);
  api.getPackInstalls.mockResolvedValue({ pack: "banking", available: 2, installs: [
    { connection_id: "c1", schema: "bank", installed: 1, recorded: true, bound_by: "user:ana", bound_at: "2026-10-26T10:00:00Z", behind: true },
  ] });
  api.getPackUpgrade.mockResolvedValue(DIFF);
});

describe("the words", () => {
  it("say the installed version and the one available, and mark a decline with its version", () => {
    expect(versionLine({ installed: 1, recorded: true, behind: true }, 2)).toBe("installed v1 · v2 available");
    expect(versionLine({ installed: 2, recorded: true, behind: false }, 2)).toBe("installed v2 · up to date");
    expect(versionLine({ installed: 1, recorded: false, behind: true }, 1)).toBe("installed before versions were kept · v1 available");
    expect(declinedMark({ declined: true, declined_in: 1 })).toBe("you declined this in v1");
    expect(declinedMark({ declined: true, declined_in: null })).toBe("you declined this");
    expect(declinedMark({ declined: false, declined_in: null })).toBe("");
  });
});

describe("PackInstalls", () => {
  it("draws nothing while installed versions are off", async () => {
    api.getPackInstalls.mockResolvedValue(null);
    const { container } = render(<PackInstalls packId="banking" />);
    await waitFor(() => expect(api.getPackInstalls).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("lists the install, shows the diff with what a person declined, and upgrades that connection", async () => {
    api.upgradePack.mockResolvedValue({ from: 1, to: 2, terms: { proposed: 1 }, alerts: { staged: [{}] }, kept_declined: 1,
      metrics: { added: 0, changed: 0, note: "" }, structure: { added: 0, changed: 0, note: "" } });
    render(<PackInstalls packId="banking" />);
    const row = await screen.findByTestId("pack-install");
    await waitFor(() => expect(row).toHaveTextContent("Lending warehouse · bank"));
    expect(within(row).getByTestId("pack-install-version")).toHaveTextContent("installed v1 · v2 available");
    fireEvent.click(within(row).getByTestId("pack-install-open"));
    const diff = await screen.findByTestId("pack-upgrade-diff");
    expect(api.getPackUpgrade).toHaveBeenCalledWith("banking", "c1", "bank");
    expect(diff).toHaveTextContent("Added · 1");
    expect(diff).toHaveTextContent("Changed · 1");
    expect(diff).toHaveTextContent("Removed · 1");
    expect(diff).toHaveTextContent("Declined, and unchanged — they stay declined · 1");
    const marks = within(diff).getAllByTestId("pack-upgrade-declined").map(m => m.textContent);
    expect(marks).toEqual([" · you declined this in v1", " · you declined this in v1"]);
    expect(diff).toHaveTextContent("fires below 0.02 → fires below 0.025");
    expect(diff).toHaveTextContent("Proposes 2 items for you to confirm");
    fireEvent.click(within(diff).getByTestId("pack-upgrade-apply"));
    await waitFor(() => expect(api.upgradePack).toHaveBeenCalledWith("banking", "c1", "bank"));
    await waitFor(() => expect(toasts.success).toHaveBeenCalled());
    expect(toasts.success.mock.calls[0][0]).toBe("Upgraded Lending warehouse to v2");
    expect(api.getPackInstalls).toHaveBeenCalledTimes(2);           // read again after the upgrade
  });

  it("keeps the button closed when there is nothing to upgrade to", async () => {
    api.getPackUpgrade.mockResolvedValue({ ...DIFF, installed: 2, upgrade_available: false, added: [], changed: [], removed: [], kept_declined: [] });
    render(<PackInstalls packId="banking" />);
    fireEvent.click(await screen.findByTestId("pack-install-open"));
    const diff = await screen.findByTestId("pack-upgrade-diff");
    expect(diff).toHaveTextContent("Nothing was added, changed or removed since v2.");
    expect(within(diff).getByTestId("pack-upgrade-apply")).toBeDisabled();
  });
});
