// @vitest-environment jsdom
/**
 * A refused admin write says the server's own reason. `assignRole` and eleven other writes
 * answered `null`/`false` on a refusal, so this panel guessed a cause ("check that you have
 * permission") for a refusal the server had already explained — and a refused revoke, member
 * removal or group deletion said nothing at all.
 */
import { fireEvent, render, screen, change } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

const assignRole = vi.fn();

// Every read the panel makes is stubbed: an unmocked one would reach the live API from jsdom.
vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getMyAccess: () => Promise.resolve({ user_id: "u1", org_id: "default", roles: ["admin"],
                                         permissions: ["admin.manage_roles"] }),
    getRoleCatalogue: () => Promise.resolve([{ name: "viewer", permissions: ["read"] }]),
    getAdminUsers: () => Promise.resolve(null),
    getGroups: () => Promise.resolve({ ladder: [], builtin_groups: [], groups: [] }),
    getActionTriggers: () => Promise.resolve([]),
    getRoleAssignments: () => Promise.resolve([]),
    assignRole: (...a: unknown[]) => assignRole(...a),
  };
});

import { RolesPanel } from "./RolesPanel";

describe("RolesPanel — a refused write", () => {
  it("shows the server's reason, not a guessed one", async () => {
    assignRole.mockRejectedValue(new Error("role 'viewer' may only be assigned inside your own organisation"));

    render(<RolesPanel />);
    change(await screen.findByPlaceholderText("user id (e.g. alice@acme.com)"),
                     { target: { value: "bo@elsewhere.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(await screen.findByRole("alert"))
      .toHaveTextContent("role 'viewer' may only be assigned inside your own organisation");
    expect(screen.queryByText(/check that you have permission/)).not.toBeInTheDocument();
  });
});
