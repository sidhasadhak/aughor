// @vitest-environment jsdom

/**
 * The Data Canvas list, redone to CLARITY (2026-10-12): three figures, "Needs you" only when a canvas needs a person,
 * then the canvases one line each. The fixtures are the live install's four canvases on 2026-10-12.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasBrowser } from "@/components/CanvasBrowser";
import type { Canvas, Connection } from "@/lib/api";

const api = vi.hoisted(() => ({ getCanvases: vi.fn(), deleteCanvas: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getCanvases: api.getCanvases,
  deleteCanvas: api.deleteCanvas,
}));

const canvas = (id: string, over: Partial<Canvas> = {}): Canvas => ({
  id, name: id, description: "", is_legacy: false, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
  scopes: [{ connection_id: "thelook", schema_name: null, tables: [] }], last_activity: null, ...over,
});
const LIVE: Canvas[] = [
  canvas("analytics", { name: "The Look Analytics", description: "Comprehensive retail data covering users and orders." }),
  canvas("ops", { name: "E-Commerce Operations Overview", last_activity: "2026-10-03T14:25:33Z" }),
  canvas("superstore", { name: "Superstore Sales Analytics", last_activity: "2026-08-15T18:15:04Z",
    scopes: [{ connection_id: "duck", schema_name: "main", tables: ["main.superstore"] }] }),
  canvas("airline", { name: "Airline And Sales Operations", last_activity: "2026-08-21T21:56:57Z",
    scopes: [{ connection_id: "workspace", schema_name: "main", tables: ["main.flights", "main.routes"] }] }),
];
const CONNS = [
  { id: "thelook", name: "theLook", conn_type: "bigquery" },
  { id: "duck", name: "DuckDB", conn_type: "duckdb" },
  { id: "workspace", name: "Workspace", conn_type: "local_upload" },
] as unknown as Connection[];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-12T12:00:00Z"));
  api.getCanvases.mockReset().mockResolvedValue(LIVE);
  api.deleteCanvas.mockReset().mockResolvedValue(undefined);
});
afterEach(() => { vi.useRealTimers(); });

const show = (props: Partial<React.ComponentProps<typeof CanvasBrowser>> = {}) => {
  const onSelect = vi.fn(), onNew = vi.fn();
  render(<Theme><CanvasBrowser connections={CONNS} onSelect={onSelect} onNew={onNew} {...props} /></Theme>);
  return { onSelect, onNew };
};

describe("the figures", () => {
  it("open the page: how many canvases and on how many connections, and how many were used in 30 days", async () => {
    show();
    expect(await screen.findByTestId("fig-canvases-value")).toHaveTextContent("4");
    expect(screen.getByTestId("fig-canvases")).toHaveTextContent("on 3 connections");
    expect(screen.getByTestId("fig-used-value")).toHaveTextContent("1 of 4");
    expect(screen.getByTestId("fig-used")).toHaveTextContent("last 8 days ago · 1 never used");
    // Which canvas was used last is the list's first row — said there, not again here.
    expect(screen.getByTestId("canvas-figures")).not.toHaveTextContent("E-Commerce Operations Overview");
  });

  it("says no canvas was asked anything, rather than inventing a latest use", async () => {
    api.getCanvases.mockResolvedValue([canvas("a"), canvas("b")]);
    show();
    expect(await screen.findByTestId("fig-used-value")).toHaveTextContent("0 of 2");
    expect(screen.getByTestId("fig-used")).toHaveTextContent("none asked anything yet");
  });
});

describe("Needs you", () => {
  it("is not drawn when nothing needs a person", async () => {
    show();
    await screen.findByTestId("canvas-figures");
    expect(screen.queryByTestId("canvas-needs")).toBeNull();
  });

  it("names a canvas whose connection is gone, with Open and Delete on its row", async () => {
    api.getCanvases.mockResolvedValue([...LIVE, canvas("lux", { name: "Lux Orders",
      scopes: [{ connection_id: "removed", schema_name: null, tables: [] }] })]);
    show();
    const needs = await screen.findByTestId("canvas-needs");
    expect(needs).toHaveAttribute("data-waiting", "true");
    const row = within(needs).getByTestId("needs-connection-gone");
    expect(row).toHaveTextContent("Lux Orders: its connection is gone");
    expect(within(row).getByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Delete…" })).toBeInTheDocument();
  });
});

describe("the list", () => {
  it("is one line per canvas, its facts as chips, sorted by last used", async () => {
    show();
    const rows = await screen.findAllByTestId("canvas-row");
    expect(rows.map(r => r.textContent)).toEqual([
      expect.stringMatching(/^E-Commerce Operations Overview.*theLook.*All tables.*used 8 days ago/),
      expect.stringMatching(/^Airline And Sales Operations.*Workspace.*2 tables.*used 51 days ago/),
      expect.stringMatching(/^Superstore Sales Analytics.*DuckDB.*1 table.*used 57 days ago/),
      expect.stringMatching(/^The Look Analytics.*never used/),
    ]);
    expect(rows[0]).not.toHaveTextContent("Data Canvas");      // a kind every row shared, said once by the rail
    expect(screen.getByTestId("canvas-list-meta")).toHaveTextContent(/^sorted by last used$/);    // the count is the figure's
  });

  it("filters by words and says how many it shows of how many", async () => {
    show();
    await screen.findAllByTestId("canvas-row");
    fireEvent.change(screen.getByLabelText("Filter canvases"), { target: { value: "duckdb" } });
    expect(screen.getAllByTestId("canvas-row")).toHaveLength(1);
    expect(screen.getByTestId("canvas-list-meta")).toHaveTextContent("1 of 4");
  });

  it("asks before deleting, and deletes the canvas it named", async () => {
    show();
    const rows = await screen.findAllByTestId("canvas-row");
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Delete E-Commerce Operations Overview" }));
    expect(await screen.findByText("Delete E-Commerce Operations Overview?")).toBeInTheDocument();
    expect(api.deleteCanvas).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("canvas-delete-confirm"));
    await vi.waitFor(() => expect(api.deleteCanvas).toHaveBeenCalledWith("ops"));
  });

  it("offers no Delete on an auto-generated canvas, and says it is one", async () => {
    api.getCanvases.mockResolvedValue([canvas("auto", { name: "Auto", is_legacy: true })]);
    show();
    const [row] = await screen.findAllByTestId("canvas-row");
    expect(row).toHaveTextContent("auto-generated");
    expect(within(row).queryByRole("button", { name: /Delete/ })).toBeNull();
  });
});

describe("withheld is said", () => {
  it("a list that could not be read says so — never that there are no canvases", async () => {
    api.getCanvases.mockRejectedValue(new Error("Failed to fetch canvases"));
    show();
    expect(await screen.findByText(/Could not read the canvases — Failed to fetch canvases/)).toBeInTheDocument();
    expect(screen.queryByTestId("canvas-none")).toBeNull();
    expect(screen.queryByTestId("canvas-figures")).toBeNull();
  });

  it("no canvases is one muted line and the way to make one", async () => {
    api.getCanvases.mockResolvedValue([]);
    const { onNew } = show();
    const none = await screen.findByTestId("canvas-none");
    expect(none).toHaveTextContent("No canvases yet");
    fireEvent.click(within(none).getByRole("button", { name: "New canvas" }));
    expect(onNew).toHaveBeenCalled();
  });
});
