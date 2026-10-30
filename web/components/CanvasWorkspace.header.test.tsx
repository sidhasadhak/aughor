// @vitest-environment jsdom

/**
 * An open Data Canvas: its header, what it is for, and the chrome around what the person made.
 *
 * The canvas is for questions and deep analysis (Arc CT, §6 item 36(l)): Chat, its Briefing (Arc BC, 2026-10-30 — the
 * dataset's own edition for a canvas on every table, its own for one that names tables), History and Artifacts. A
 * dashboard is a person's, in the Briefing page. The header's give-and-take was fixed while the canvas
 * briefly had a fourth tab, and stands on its own. Redone to CLARITY (2026-10-12): the header says the name, what it is
 * in a line and its facts as chips; the landing no longer repeats them; a question asked many times is one history row;
 * a read that failed says so instead of showing an empty list.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasWorkspace } from "@/components/CanvasWorkspace";
import { DEEP_ANALYSIS_MODE, type Canvas, type Connection } from "@/lib/api";

const api = vi.hoisted(() => ({
  getSystemFlags: vi.fn().mockResolvedValue({}),
  getCanvasHistory: vi.fn(),
  getCanvasArtifacts: vi.fn(),
  getCanvasDocuments: vi.fn(),
}));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getSystemFlags: api.getSystemFlags,
  getCanvasHistory: api.getCanvasHistory,
  getCanvasArtifacts: api.getCanvasArtifacts,
  getCanvasDocuments: api.getCanvasDocuments,
  listDocuments: vi.fn().mockResolvedValue([]),
  deleteCanvasArtifact: vi.fn().mockResolvedValue(undefined),
  updateCanvas: vi.fn(),
}));
// The board is what the person made; the test holds what the canvas hands it — the landing — and nothing it draws.
vi.mock("@/components/ChatPanel", () => ({
  ChatPanel: ({ capabilities, initialQuestion, initialMode }: { capabilities?: React.ReactNode; initialQuestion?: string; initialMode?: string }) =>
    <div data-testid="chat" data-question={initialQuestion} data-mode={initialMode}>{capabilities}</div>,
}));
vi.mock("@/components/brief/BriefingEdition", () => ({
  BriefingEdition: (p: { canvasId?: string; connectionId: string; workspaceId?: string; onDeepAnalysis?: (q: string) => void }) => (
    <div data-testid="edition" data-canvas={p.canvasId} data-conn={p.connectionId} data-workspace={p.workspaceId}>
      <span role="button" tabIndex={0} onClick={() => p.onDeepAnalysis?.("Why did returns fall?")}>Take it deeper</span>
    </div>
  ),
}));
vi.mock("@/components/HistoryDetailPanel", () => ({ HistoryDetailPanel: () => null }));
vi.mock("@/components/ConfigurePanel", () => ({ ConfigurePanel: () => null }));
vi.mock("@/components/LifecyclePanel", () => ({ LifecyclePanel: () => null }));

const CANVAS: Canvas = {
  id: "cv1", name: "Returns", description: "", is_legacy: false, created_at: "", updated_at: "",
  scopes: [{ connection_id: "thelook", schema_name: "thelook", tables: ["thelook.order_items"] }],
};
const CONNECTIONS = [{ id: "thelook", name: "theLook", conn_type: "bigquery" }] as unknown as Connection[];

beforeEach(() => {
  api.getCanvasHistory.mockReset().mockResolvedValue([]);
  api.getCanvasArtifacts.mockReset().mockResolvedValue([]);
  api.getCanvasDocuments.mockReset().mockResolvedValue([]);
});

const show = (canvas: Canvas = CANVAS, connections: Connection[] = CONNECTIONS) =>
  render(<Theme><CanvasWorkspace canvas={canvas} connections={connections} onClose={vi.fn()} onCanvasUpdate={vi.fn()} workspaceId="default" /></Theme>);
const tabs = () => screen.getAllByRole("button").map(b => b.textContent?.trim()).filter(t => ["Chat", "Briefing", "History", "Artifacts", "Cockpit"].includes(t ?? ""));
const settle = () => new Promise(r => setTimeout(r, 10));

describe("the Data Canvas", () => {
  it("has its four views, the Briefing after Chat, and no dashboard", async () => {
    show();
    await settle();
    expect(tabs()).toEqual(["Chat", "Briefing", "History", "Artifacts"]);
    expect(screen.getByRole("button", { name: "Chat" }).getAttribute("aria-pressed")).toBe("true");   // still opens on Chat
    expect(api.getSystemFlags).not.toHaveBeenCalled();      // it no longer asks
  });

  it("reads the canvas's Briefing only once the tab is opened, and takes a question from it into deep analysis", async () => {
    show();
    await settle();
    expect(screen.queryByTestId("edition")).toBeNull();                                    // opening a canvas reads none
    fireEvent.click(screen.getByRole("button", { name: "Briefing" }));
    const edition = await screen.findByTestId("edition");
    expect(edition.dataset).toMatchObject({ canvas: "cv1", conn: "thelook", workspace: "default" });
    fireEvent.click(screen.getByRole("button", { name: "Take it deeper" }));
    expect(screen.getByRole("button", { name: "Chat" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("chat").dataset).toMatchObject({ question: "Why did returns fall?", mode: DEEP_ANALYSIS_MODE });
  });

  it("keeps every tool in one menu, and a way back before the name", () => {
    show();
    expect(screen.getByTestId("canvas-tools")).toHaveTextContent("Tools");
    expect(screen.queryByRole("button", { name: /^Configure$/ })).toBeNull();     // no longer a button of its own
    expect(screen.getByTestId("canvas-back")).toHaveAttribute("title", "Back to all canvases");
  });
});

describe("the header, when the row is short of room", () => {
  // jsdom measures nothing, so this holds what the row is TOLD to do; that it does it was seen
  // in a browser at 1176px, where a long name and four tabs had made the row wider than its
  // box and the workspace slid sideways under the sidebar.
  it("lets the description give way first, then the connection's chip, then the name — and nothing else", () => {
    show({ ...CANVAS, name: "E-Commerce Operations Overview", description: "Orders, items and returns for the online shop." });

    const name = screen.getByTestId("canvas-name");
    expect(name).toHaveTextContent("E-Commerce Operations Overview");
    expect(name).toHaveAttribute("title", "E-Commerce Operations Overview");     // the whole name, on hover
    expect(name).toHaveStyle({ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
    expect(name).toHaveStyle({ minWidth: "64px", flexShrink: "1" });              // room for a word
    // What it is, in one line — the first to give way, whole on hover.
    const what = screen.getByTestId("canvas-what");
    expect(what).toHaveAttribute("title", "Orders, items and returns for the online shop.");
    // a basis of 0: it takes only the room the name and chips leave, so it never cuts the name
    expect(what).toHaveStyle({ minWidth: "0", flexGrow: "1", flexShrink: "1", flexBasis: "0%", overflow: "hidden", whiteSpace: "nowrap" });
    // The connection's chip gives way next, and says the whole of itself on hover.
    const chip = screen.getByTestId("canvas-connection");
    expect(chip).toHaveStyle({ flexShrink: "3", minWidth: "56px", overflow: "hidden" });
    expect(chip).toHaveAttribute("title", "theLook · BigQuery");
    expect(chip).toHaveTextContent("theLook");
    expect(screen.getByTestId("canvas-tabs")).toHaveStyle({ flexShrink: "0" });
  });

  it("says a canvas's connection is gone, in amber, once the connections are known", () => {
    show({ ...CANVAS, scopes: [{ connection_id: "removed", schema_name: null, tables: [] }] });
    expect(screen.getByTestId("canvas-connection-gone")).toHaveTextContent("connection gone");
  });

  it("reads a connection of another workspace as there, not gone, and names it", () => {
    // 2026-10-12: judged against this workspace's connections alone, two live canvases read "connection gone".
    const other = { ...CONNECTIONS[0], id: "duck", name: "DuckDB", conn_type: "duckdb" } as Connection;
    render(<Theme><CanvasWorkspace canvas={{ ...CANVAS, scopes: [{ connection_id: "duck", schema_name: "main", tables: [] }] }}
      connections={CONNECTIONS} allConnections={[...CONNECTIONS, other]} onClose={vi.fn()} onCanvasUpdate={vi.fn()} /></Theme>);
    expect(screen.queryByTestId("canvas-connection-gone")).toBeNull();
    expect(screen.getByTestId("canvas-head")).toHaveTextContent("DuckDB");
  });

  it("says nothing is gone while the connections are not read yet", () => {
    show(CANVAS, []);
    expect(screen.queryByTestId("canvas-connection-gone")).toBeNull();
  });

  it("says a pinned document that was deleted, in amber", async () => {
    api.getCanvasDocuments.mockResolvedValue([{ doc_id: "d1", missing: false }, { doc_id: "d2", missing: true }]);
    show({ ...CANVAS, doc_ids: ["d1", "d2"] });
    expect(await screen.findByTestId("canvas-docs-missing")).toHaveTextContent("2 documents pinned · 1 deleted");
  });
});

describe("the landing", () => {
  it("invites a question about what the canvas reads, without repeating the header's name or description", () => {
    show({ ...CANVAS, description: "Orders, items and returns." });
    const landing = screen.getByTestId("canvas-landing");
    expect(landing).toHaveTextContent("What do you want to know about thelook.order_items?");
    expect(landing).not.toHaveTextContent("Returns");
    expect(landing).not.toHaveTextContent("Orders, items and returns.");
  });

  it("names the connection for a canvas over all of it", () => {
    show({ ...CANVAS, scopes: [{ connection_id: "thelook", schema_name: null, tables: [] }] });
    expect(screen.getByTestId("canvas-landing")).toHaveTextContent("What do you want to know about theLook?");
  });
});

describe("the history", () => {
  it("says a question asked many times once, with its count", async () => {
    const run = (id: string, at: string) => ({ id, question: "What was total revenue in July 2026?", status: "complete",
      started_at: at });
    api.getCanvasHistory.mockResolvedValue([run("r1", "2026-10-03T14:23:57Z"), run("r2", "2026-10-03T13:53:57Z"),
      run("r3", "2026-10-01T13:53:57Z")]);
    show();
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    const rows = await screen.findAllByTestId("canvas-history-row");
    expect(rows).toHaveLength(1);
    expect(screen.getByTestId("canvas-history-count")).toHaveTextContent("×3");
    expect(screen.getByTestId("canvas-history-meta")).toHaveTextContent("3 runs · 1 question");
    // What it leaves out is said: other canvases' runs, and deep analyses that did not finish.
    expect(screen.getByTestId("canvas-history-scope")).toHaveAttribute("title",
      expect.stringContaining("did not finish"));
  });

  it("says a failed read failed — never that nothing was asked", async () => {
    api.getCanvasHistory.mockRejectedValue(new Error("history store locked"));
    show();
    expect(await screen.findByText(/Could not read this canvas's history — history store locked/)).toBeInTheDocument();
    expect(screen.queryByText("Nothing asked on this canvas yet.")).toBeNull();
  });
});

describe("the artifacts", () => {
  it("says a failed read failed — never that nothing was saved", async () => {
    api.getCanvasArtifacts.mockRejectedValue(new Error("Failed to fetch artifacts"));
    show();
    expect(await screen.findByText(/Could not read this canvas's artifacts/)).toBeInTheDocument();
    expect(screen.queryByText("Nothing saved on this canvas yet.")).toBeNull();
  });
});
