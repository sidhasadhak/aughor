/**
 * Where an upload lands. Until 2026-10-23 the answer was a constant — the built-in `workspace`
 * connection — whatever workspace the reader stood in (the Olist run, gaps 1 and 2).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getWorkspace: vi.fn(),
  getConnections: vi.fn(),
  addConnection: vi.fn(),
}));
vi.mock("./api", () => api);

import { createUploadTarget, resolveUploadTarget, uploadsNameFor } from "./uploadTarget";

const conn = (id: string, conn_type: string, name = id) => ({ id, name, conn_type, dsn_preview: "", schema_name: null, builtin: false });

beforeEach(() => {
  api.getWorkspace.mockReset();
  api.getConnections.mockReset();
  api.addConnection.mockReset();
});

describe("resolveUploadTarget", () => {
  it("is the built-in Workspace when no workspace is selected, and for the Default workspace", async () => {
    expect(await resolveUploadTarget(undefined)).toEqual({ id: "workspace", label: "Workspace" });
    api.getWorkspace.mockResolvedValue({ id: "default", name: "Default", is_default: true, connection_ids: ["workspace", "pg1"] });
    api.getConnections.mockResolvedValue([conn("workspace", "local_upload", "Workspace"), conn("pg1", "postgres")]);
    expect(await resolveUploadTarget("default")).toEqual({ id: "workspace", label: "Workspace" });
  });

  it("is the workspace's own uploads connection when it has one", async () => {
    api.getWorkspace.mockResolvedValue({ id: "w2", name: "Olist", is_default: false, connection_ids: ["u1", "pg1"] });
    api.getConnections.mockResolvedValue([conn("workspace", "local_upload", "Workspace"), conn("u1", "local_upload", "Olist uploads"), conn("pg1", "postgres")]);
    expect(await resolveUploadTarget("w2")).toEqual({ id: "u1", label: "Olist uploads" });
  });

  it("keeps the built-in one for a workspace that was given it by hand — its files are already there", async () => {
    api.getWorkspace.mockResolvedValue({ id: "w2", name: "Olist", is_default: false, connection_ids: ["workspace"] });
    api.getConnections.mockResolvedValue([conn("workspace", "local_upload", "Workspace")]);
    expect(await resolveUploadTarget("w2")).toEqual({ id: "workspace", label: "Workspace" });
  });

  it("is null — not the built-in one — for a workspace with no uploads space yet", async () => {
    api.getWorkspace.mockResolvedValue({ id: "w3", name: "Acme", is_default: false, connection_ids: ["pg1"] });
    api.getConnections.mockResolvedValue([conn("workspace", "local_upload", "Workspace"), conn("pg1", "postgres")]);
    expect(await resolveUploadTarget("w3")).toBeNull();
  });
});

describe("createUploadTarget", () => {
  it("makes a local-upload connection named after the workspace, as a member of it", async () => {
    api.getWorkspace.mockResolvedValue({ id: "w3", name: "Acme", is_default: false, connection_ids: [] });
    api.addConnection.mockResolvedValue({ id: "u9", message: "Connection added", test_result: "ok" });
    expect(await createUploadTarget("w3")).toEqual({ id: "u9", label: "Acme uploads" });
    expect(api.addConnection).toHaveBeenCalledWith("Acme uploads", "local_upload", "local://", undefined, {}, "w3");
  });

  it("names the space after the workspace, with a fallback for a blank name", () => {
    expect(uploadsNameFor("Olist")).toBe("Olist uploads");
    expect(uploadsNameFor("  ")).toBe("Workspace uploads");
  });
});
