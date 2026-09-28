// @vitest-environment jsdom

/**
 * The Cockpit tab's place in the Data Canvas (Arc CT-4, flag `cockpit.composed`).
 *
 * Off, the canvas has its three tabs and the cockpit is not mounted at all — so no card is
 * run for a screen nobody can open. On, the tab is there, and the cockpit mounts when it is
 * first opened, not before.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasWorkspace } from "@/components/CanvasWorkspace";
import type { Canvas, Connection } from "@/lib/api";

const api = vi.hoisted(() => ({ getSystemFlags: vi.fn() }));
const cockpit = vi.hoisted(() => ({ mounts: [] as Record<string, unknown>[] }));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getSystemFlags: api.getSystemFlags,
  getCanvasHistory: vi.fn().mockResolvedValue([]),
  getCanvasArtifacts: vi.fn().mockResolvedValue([]),
  getCanvasDocuments: vi.fn().mockResolvedValue([]),
  listDocuments: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/components/ChatPanel", () => ({ ChatPanel: () => <div data-testid="chat" /> }));
vi.mock("@/components/HistoryDetailPanel", () => ({ HistoryDetailPanel: () => null }));
vi.mock("@/components/ConfigurePanel", () => ({ ConfigurePanel: () => null }));
vi.mock("@/components/LifecyclePanel", () => ({ LifecyclePanel: () => null }));
vi.mock("@/components/cockpit/CockpitTab", () => ({
  CockpitTab: (props: Record<string, unknown>) => { cockpit.mounts.push(props); return <div data-testid="cockpit-tab-stub" />; },
}));

const CANVAS: Canvas = {
  id: "cv1", name: "Returns", description: "", is_legacy: false, created_at: "", updated_at: "",
  scopes: [{ connection_id: "thelook", schema_name: "thelook", tables: ["thelook.order_items"] }],
};
const CONNECTIONS = [{ id: "thelook", name: "theLook", conn_type: "bigquery" }] as unknown as Connection[];

const show = (canvas: Canvas = CANVAS) =>
  render(<CanvasWorkspace canvas={canvas} connections={CONNECTIONS} onClose={vi.fn()} onCanvasUpdate={vi.fn()} />);
const tabs = () => screen.getAllByRole("button").map(b => b.textContent?.trim()).filter(t => ["Chat", "History", "Artifacts", "Cockpit"].includes(t ?? ""));

beforeEach(() => {
  api.getSystemFlags.mockReset();
  cockpit.mounts.length = 0;
});

describe("the header, when the row is short of room", () => {
  // jsdom measures nothing, so this holds what the row is TOLD to do; that it does it was seen
  // in a browser at 1176px, where a long name and four tabs had made the row wider than its
  // box and the workspace slid sideways under the sidebar.
  it("lets the canvas's name and the connection's badge give way, and nothing else", async () => {
    api.getSystemFlags.mockResolvedValue({ "cockpit.composed": { value: true } });
    show({ ...CANVAS, name: "E-Commerce Operations Overview" });
    await waitFor(() => expect(tabs()).toContain("Cockpit"));

    const name = screen.getByTestId("canvas-name");
    expect(name).toHaveTextContent("E-Commerce Operations Overview");
    expect(name).toHaveAttribute("title", "E-Commerce Operations Overview");     // the whole name, on hover
    expect(name).toHaveStyle({ minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
    expect(name.parentElement).toHaveStyle({ minWidth: "64px", flexShrink: "1" });   // room for a word
    // The connection's badge gives way first, and says the whole of itself on hover.
    const badge = screen.getByTestId("canvas-connection");
    expect(badge).toHaveStyle({ flexShrink: "3", minWidth: "56px", overflow: "hidden" });
    expect(badge).toHaveAttribute("title", "theLook bigquery");
    expect(badge).toHaveTextContent("theLookbigquery");
    expect(screen.getByTestId("canvas-tabs")).toHaveStyle({ flexShrink: "0" });
  });
});

describe("with the flag off", () => {
  it.each([
    ["absent from the flags", {}],
    ["off", { "cockpit.composed": { value: false } }],
  ])("the canvas has its three tabs and no cockpit is mounted (%s)", async (_what, flags) => {
    api.getSystemFlags.mockResolvedValue(flags);
    show();
    await waitFor(() => expect(api.getSystemFlags).toHaveBeenCalled());
    await new Promise(r => setTimeout(r, 10));

    expect(tabs()).toEqual(["Chat", "History", "Artifacts"]);
    expect(screen.queryByTestId("cockpit-tab-stub")).toBeNull();
    expect(cockpit.mounts).toEqual([]);
  });

  it("the flags being unreadable is the flag being off", async () => {
    api.getSystemFlags.mockRejectedValue(new Error("the API is down"));
    show();
    await new Promise(r => setTimeout(r, 10));
    expect(tabs()).toEqual(["Chat", "History", "Artifacts"]);
  });
});

describe("with the flag on", () => {
  beforeEach(() => api.getSystemFlags.mockResolvedValue({ "cockpit.composed": { value: true } }));

  it("adds the tab, and mounts the cockpit only when it is opened", async () => {
    show();
    await screen.findByRole("button", { name: "Cockpit" });
    expect(tabs()).toEqual(["Chat", "History", "Artifacts", "Cockpit"]);
    expect(cockpit.mounts).toEqual([]);                       // nothing ran for a tab nobody opened

    fireEvent.click(screen.getByRole("button", { name: "Cockpit" }));
    expect(screen.getByTestId("cockpit-tab-stub")).toBeInTheDocument();
    expect(cockpit.mounts.at(-1)).toEqual({ canvasId: "cv1", connectionId: "thelook", schema: "thelook", active: true });
  });

  it("keeps the cockpit mounted behind another tab, and tells it that it is not showing", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Cockpit" }));
    fireEvent.click(screen.getByRole("button", { name: "History" }));

    expect(screen.getByTestId("cockpit-tab-stub")).toBeInTheDocument();
    expect(cockpit.mounts.at(-1)).toMatchObject({ canvasId: "cv1", active: false });
  });

  it("another canvas starts with its cockpit unopened", async () => {
    const { rerender } = show();
    fireEvent.click(await screen.findByRole("button", { name: "Cockpit" }));
    expect(screen.getByTestId("cockpit-tab-stub")).toBeInTheDocument();

    rerender(<CanvasWorkspace canvas={{ ...CANVAS, id: "cv2", name: "Revenue" }} connections={CONNECTIONS} onClose={vi.fn()} onCanvasUpdate={vi.fn()} />);
    await waitFor(() => expect(screen.queryByTestId("cockpit-tab-stub")).toBeNull());
  });
});
