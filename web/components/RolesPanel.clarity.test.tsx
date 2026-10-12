// @vitest-environment jsdom
/**
 * Settings ▸ Access, redone to CLARITY (2026-10-12). Pinned: the figures row (who you are, the assignments, the
 * function groups, how much of the ledger carries a person), the two rules "Needs you" holds — no recorded call
 * carries a user; a function group has no members, with the button that opens it — and the one muted line when
 * neither holds. A role's permissions are behind its Details, not printed for every role.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminUsers, GroupsCatalogue } from "@/lib/api";

const api = vi.hoisted(() => ({
  getMyAccess: vi.fn(), getRoleCatalogue: vi.fn(), getAdminUsers: vi.fn(), getGroups: vi.fn(),
  getActionTriggers: vi.fn(), getRoleAssignments: vi.fn(), getGroupMembers: vi.fn(), getLevelGrants: vi.fn(),
  assignRole: vi.fn(), revokeRole: vi.fn(), saveGroup: vi.fn(), deleteGroup: vi.fn(), addGroupMember: vi.fn(),
  removeGroupMember: vi.fn(), addLevelGrant: vi.fn(), removeLevelGrant: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { RolesPanel } from "./RolesPanel";

const OWNER_PERMS = ["admin.manage_org", "admin.manage_roles", "analysis.run", "resource.read"];
const GROUPS: GroupsCatalogue = {
  ladder: ["view", "subscribe", "edit"],
  builtin_groups: [
    { id: "viewer", name: "Viewer", kind: "builtin", description: "", channel_trigger_id: "", levels: { "*": "view" } },
    { id: "owner", name: "Owner", kind: "builtin", description: "", channel_trigger_id: "", levels: { "*": "own" } },
  ],
  groups: [{ id: "supply-chain", name: "Supply chain", kind: "function", description: "", channel_trigger_id: "" }],
};
const users = (over: Partial<AdminUsers> = {}): AdminUsers => ({
  org_id: "default", users: [], total_calls: 2223, unattributed_calls: 2223, coverage: 0,
  identity_required: false, oidc_configured: false, ...over,
});

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getMyAccess.mockResolvedValue({ user_id: null, actor: "amit", signed_in: false, org_id: "default",
    roles: ["owner"], permissions: OWNER_PERMS });
  api.getRoleCatalogue.mockResolvedValue([
    { name: "viewer", label: "Viewer", description: "Read-only access.", permissions: ["resource.read"] },
    { name: "owner", label: "Owner", description: "Full control.", permissions: OWNER_PERMS },
  ]);
  api.getAdminUsers.mockResolvedValue(users());
  api.getGroups.mockResolvedValue(GROUPS);
  api.getActionTriggers.mockResolvedValue([]);
  api.getRoleAssignments.mockResolvedValue([{ org_id: "default", user_id: "mallory", role: "owner", created_at: "", updated_at: "" }]);
  api.getGroupMembers.mockResolvedValue([]);
  api.getLevelGrants.mockResolvedValue([]);
});

const value = (id: string) => screen.getByTestId(`${id}-value`);

describe("Settings ▸ Access", () => {
  it("opens on who you are, the assignments, the groups and the share of calls attributed", async () => {
    render(<RolesPanel />);
    await waitFor(() => expect(value("fig-you")).toHaveTextContent("Owner"));
    expect(screen.getByTestId("fig-you")).toHaveTextContent("amit · not signed in · org default");
    expect(value("fig-assignments")).toHaveTextContent("1");
    expect(screen.getByTestId("fig-assignments")).toHaveTextContent("1 Owner");
    expect(value("fig-groups")).toHaveTextContent("1");
    expect(value("fig-attributed")).toHaveTextContent("0%");
    expect(screen.getByTestId("fig-attributed")).toHaveTextContent("of 2,223 recorded calls");
  });

  it("needs you for calls that carry no user, and for a group with no members — whose button opens it", async () => {
    render(<RolesPanel />);
    const attribution = await screen.findByTestId("needs-attribution");
    expect(attribution).toHaveTextContent("No recorded call carries a user");
    expect(attribution).toHaveTextContent("Attribution starts once OIDC is configured");
    const empty = await screen.findByTestId("needs-empty-group");
    expect(empty).toHaveTextContent("Supply chain has no members");
    fireEvent.click(within(empty).getByRole("button", { name: "Add members" }));
    await waitFor(() => expect(api.getLevelGrants).toHaveBeenCalledWith({ principal: "group:supply-chain" }));
    expect(await screen.findByLabelText("Add a member to Supply chain")).toBeInTheDocument();
  });

  it("says nothing needs you when calls carry people and every group has members", async () => {
    api.getAdminUsers.mockResolvedValue(users({ coverage: 0.5, unattributed_calls: 1000 }));
    api.getGroupMembers.mockResolvedValue(["user:ana@corp"]);
    render(<RolesPanel />);
    await waitFor(() => expect(screen.getByTestId("access-needs")).toHaveAttribute("data-waiting", "false"));
    expect(screen.getByTestId("access-needs")).toHaveTextContent("Nothing needs you");
    expect(screen.queryByTestId("needs-attribution")).toBeNull();
    expect(screen.queryByTestId("needs-empty-group")).toBeNull();
  });

  it("keeps each role's permissions behind its Details", async () => {
    render(<RolesPanel />);
    const roles = await screen.findByTestId("access-roles");
    expect(within(roles).queryByText("admin.manage_roles")).toBeNull();
    fireEvent.click(within(roles).getByRole("button", { name: /^4 permissions/ }));
    expect(within(roles).getByText("admin.manage_roles")).toBeInTheDocument();
  });
});
