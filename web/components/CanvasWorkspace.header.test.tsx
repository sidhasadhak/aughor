// @vitest-environment jsdom

/**
 * The Data Canvas's header, and what the canvas is for.
 *
 * The canvas is for questions and deep analysis (Arc CT, §6 item 36(l)): it has its three tabs whatever the
 * cockpit flag says. A cockpit is a person's, in the Briefing. The header's give-and-take was
 * fixed while the canvas briefly had a fourth tab, and stands on its own.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanvasWorkspace } from "@/components/CanvasWorkspace";
import type { Canvas, Connection } from "@/lib/api";

const api = vi.hoisted(() => ({ getSystemFlags: vi.fn().mockResolvedValue({ "cockpit.composed": { value: true } }) }));

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

const CANVAS: Canvas = {
  id: "cv1", name: "Returns", description: "", is_legacy: false, created_at: "", updated_at: "",
  scopes: [{ connection_id: "thelook", schema_name: "thelook", tables: ["thelook.order_items"] }],
};
const CONNECTIONS = [{ id: "thelook", name: "theLook", conn_type: "bigquery" }] as unknown as Connection[];

const show = (canvas: Canvas = CANVAS) =>
  render(<CanvasWorkspace canvas={canvas} connections={CONNECTIONS} onClose={vi.fn()} onCanvasUpdate={vi.fn()} />);
const tabs = () => screen.getAllByRole("button").map(b => b.textContent?.trim()).filter(t => ["Chat", "History", "Artifacts", "Cockpit"].includes(t ?? ""));

describe("the Data Canvas", () => {
  it("has its three tabs and no cockpit, with the cockpit flag on", async () => {
    show();
    await new Promise(r => setTimeout(r, 10));
    expect(tabs()).toEqual(["Chat", "History", "Artifacts"]);
    expect(api.getSystemFlags).not.toHaveBeenCalled();      // it no longer asks
  });
});

describe("the header, when the row is short of room", () => {
  // jsdom measures nothing, so this holds what the row is TOLD to do; that it does it was seen
  // in a browser at 1176px, where a long name and four tabs had made the row wider than its
  // box and the workspace slid sideways under the sidebar.
  it("lets the canvas's name and the connection's badge give way, and nothing else", () => {
    show({ ...CANVAS, name: "E-Commerce Operations Overview" });

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
