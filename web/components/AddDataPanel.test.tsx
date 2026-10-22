// @vitest-environment jsdom
/**
 * An upload lands in the workspace the reader stands in. Until 2026-10-23 `AddDataPanel` carried the
 * built-in connection's id as a constant, so a new customer's nine files landed in a connection
 * their workspace did not hold, beside everyone else's (the Olist run, gaps 1 and 2).
 *
 * The panel is rendered whole: the upload tile is picked, Bulk import chosen, files dropped on the
 * panel's own hidden input — the same handler a drop runs — and the request's connection id read.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Theme } from "@radix-ui/themes";

const api = vi.hoisted(() => ({
  getConnectorTypes: vi.fn(),
  getWorkspace: vi.fn(),
  getConnections: vi.fn(),
  addConnection: vi.fn(),
  listConnectionFiles: vi.fn(),
  listConnectionSchemas: vi.fn(),
  bulkUploadFilesToConnection: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { AddDataPanel } from "./AddDataPanel";

const UPLOAD_TYPE = { type: "local_upload", dsn_preview: "local://", category: "file", fields: [], available: true };
const conn = (id: string, conn_type: string, name = id) => ({ id, name, conn_type, dsn_preview: "", schema_name: null, builtin: false });

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getConnectorTypes.mockResolvedValue([UPLOAD_TYPE]);
  api.listConnectionFiles.mockResolvedValue([]);
  api.listConnectionSchemas.mockResolvedValue(["main"]);
  api.bulkUploadFilesToConnection.mockResolvedValue({ results: [{ filename: "orders.csv", status: "ok", table_name: "orders" }] });
  api.addConnection.mockResolvedValue({ id: "u9", message: "Connection added", test_result: "ok" });
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
});
afterEach(() => vi.unstubAllGlobals());

async function dropOneFile(workspaceId: string | undefined, onAdded = vi.fn(async () => true)) {
  const { container } = render(<Theme><AddDataPanel onClose={() => {}} onAdded={onAdded} workspaceId={workspaceId} /></Theme>);
  fireEvent.click(await screen.findByText("Create or modify table"));
  fireEvent.click(await screen.findByText("Bulk import"));
  await act(async () => {});                                   // the target resolves
  const input = container.querySelector('input[type="file"][multiple]') as HTMLInputElement;
  expect(input).not.toBeNull();
  const file = new File(["order_id,price\n1,9.9\n"], "orders.csv", { type: "text/csv" });
  await act(async () => { fireEvent.change(input, { target: { files: [file] } }); });
  await waitFor(() => expect(api.bulkUploadFilesToConnection).toHaveBeenCalled());
  return { container, onAdded };
}

describe("where an upload lands", () => {
  it("goes to the workspace's own uploads connection when it has one", async () => {
    api.getWorkspace.mockResolvedValue({ id: "w2", name: "Olist", is_default: false, connection_ids: ["u1"] });
    api.getConnections.mockResolvedValue([conn("workspace", "local_upload", "Workspace"), conn("u1", "local_upload", "Olist uploads")]);
    await dropOneFile("w2");
    expect(api.bulkUploadFilesToConnection.mock.calls[0][0]).toBe("u1");
    expect(api.addConnection).not.toHaveBeenCalled();
    expect(screen.getAllByText("Olist uploads", { exact: false }).length).toBeGreaterThan(0);   // the heading and the table list both name it
  });

  it("makes the workspace its own uploads connection on the first upload, and shows it in the catalogue", async () => {
    api.getWorkspace.mockResolvedValue({ id: "w3", name: "Acme", is_default: false, connection_ids: [] });
    api.getConnections.mockResolvedValue([conn("workspace", "local_upload", "Workspace")]);
    const { onAdded } = await dropOneFile("w3");
    expect(api.addConnection).toHaveBeenCalledWith("Acme uploads", "local_upload", "local://", undefined, {}, "w3");
    expect(onAdded).toHaveBeenCalledWith("u9");
    expect(api.bulkUploadFilesToConnection.mock.calls[0][0]).toBe("u9");
  });

  it("still goes to the built-in Workspace in the Default workspace, and makes nothing", async () => {
    api.getWorkspace.mockResolvedValue({ id: "default", name: "Default", is_default: true, connection_ids: ["workspace"] });
    api.getConnections.mockResolvedValue([conn("workspace", "local_upload", "Workspace")]);
    await dropOneFile("default");
    expect(api.bulkUploadFilesToConnection.mock.calls[0][0]).toBe("workspace");
    expect(api.addConnection).not.toHaveBeenCalled();
  });
});
