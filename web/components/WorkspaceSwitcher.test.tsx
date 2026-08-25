// @vitest-environment jsdom
/**
 * The workspace switcher's membership editor — the surface whose absence made
 * every user-created workspace a dead-end. Before it, creation always sent an
 * empty connection list and nothing anywhere could add a connection afterwards:
 * the new workspace cleared the selected connection and every panel rendered
 * blank, permanently. These tests pin the escape routes: create lands in the
 * editor, membership saves through the PUT, and delete is reachable (and
 * confirm-gated, and absent on the default workspace).
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Connection, Workspace } from "@/lib/api";
import { WorkspaceSwitcher } from "@/components/WorkspaceSwitcher";

const ws = (over: Partial<Workspace> = {}): Workspace => ({
  id: "ws1", name: "Sales", description: "", connection_ids: [],
  is_default: false, created_at: "", updated_at: "", ...over,
});

const conn = (id: string, name: string) => ({ id, name } as Connection);

const noop = async () => {};
const neverCreate = async () => { throw new Error("unexpected create"); };

function show(over: {
  workspaces?: Workspace[];
  allConnections?: Connection[];
  onCreateWorkspace?: (name: string) => Promise<Workspace>;
  onUpdateWorkspace?: (id: string, ids: string[]) => Promise<void>;
  onDeleteWorkspace?: (id: string) => Promise<void>;
  onWorkspaceChange?: (id: string) => void;
} = {}) {
  return render(
    <WorkspaceSwitcher
      workspaces={over.workspaces ?? [ws()]}
      selectedWorkspace="ws1"
      allConnections={over.allConnections ?? [conn("c1", "Postgres"), conn("c2", "Uploads")]}
      onWorkspaceChange={over.onWorkspaceChange ?? (() => {})}
      onCreateWorkspace={over.onCreateWorkspace ?? neverCreate}
      onUpdateWorkspace={over.onUpdateWorkspace ?? noop}
      onDeleteWorkspace={over.onDeleteWorkspace ?? noop}
    />,
  );
}

const openDropdown = () =>
  userEvent.click(screen.getByRole("button", { name: /switch workspace/i }));

describe("WorkspaceSwitcher membership editing", () => {
  it("creating a workspace lands in its membership editor, not on a dead list", async () => {
    const created = ws({ id: "ws9", name: "Finance" });
    const onCreate = vi.fn().mockResolvedValue(created);
    show({ workspaces: [ws(), created], onCreateWorkspace: onCreate });
    await openDropdown();
    await userEvent.click(screen.getByRole("button", { name: /new workspace/i }));
    await userEvent.type(screen.getByPlaceholderText(/workspace name/i), "Finance");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(onCreate).toHaveBeenCalledWith("Finance");
    // The editor for the NEW workspace is open: its connections header plus a
    // checkbox per org connection, ready to populate.
    expect(await screen.findByText(/Finance · connections/i)).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("saves the checked connections through onUpdateWorkspace", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    show({ onUpdateWorkspace: onUpdate });
    await openDropdown();
    await userEvent.click(screen.getByRole("button", { name: /manage sales/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /postgres/i }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onUpdate).toHaveBeenCalledWith("ws1", ["c1"]);
  });

  it("unchecking removes a member on save", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    show({ workspaces: [ws({ connection_ids: ["c1", "c2"] })], onUpdateWorkspace: onUpdate });
    await openDropdown();
    await userEvent.click(screen.getByRole("button", { name: /manage sales/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /postgres/i }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onUpdate).toHaveBeenCalledWith("ws1", ["c2"]);
  });

  it("deletes only after the user confirms", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    show({ onDeleteWorkspace: onDelete });
    await openDropdown();
    await userEvent.click(screen.getByRole("button", { name: /manage sales/i }));
    await userEvent.click(screen.getByRole("button", { name: /delete this workspace/i }));
    expect(onDelete).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: /delete this workspace/i }));
    expect(onDelete).toHaveBeenCalledWith("ws1");
    confirm.mockRestore();
  });

  it("offers no delete on the default workspace", async () => {
    show({ workspaces: [ws({ is_default: true, name: "Default" })] });
    await openDropdown();
    await userEvent.click(screen.getByRole("button", { name: /manage default/i }));
    expect(await screen.findByText(/Default · connections/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete this workspace/i }))
      .not.toBeInTheDocument();
  });

  it("says what to do when the org has no connections at all", async () => {
    show({ allConnections: [] });
    await openDropdown();
    await userEvent.click(screen.getByRole("button", { name: /manage sales/i }));
    expect(await screen.findByText(/add one first/i)).toBeInTheDocument();
  });

  it("counts granted catalogs into what a workspace sees", async () => {
    // Membership 1 + one explicit grant = 2 visible; counting membership alone
    // read a granted workspace as smaller than what its panels actually show.
    show({ workspaces: [ws({ connection_ids: ["c1"], accessible_connection_ids: ["c1", "c2"] })] });
    await openDropdown();
    expect(await screen.findByText(/2 connections · 1 via grant/)).toBeInTheDocument();
  });

  it("still switches workspaces from the list", async () => {
    const onChange = vi.fn();
    show({ workspaces: [ws(), ws({ id: "ws2", name: "Ops" })], onWorkspaceChange: onChange });
    await openDropdown();
    await userEvent.click(screen.getByRole("button", { name: /^Ops/ }));
    expect(onChange).toHaveBeenCalledWith("ws2");
  });
});
