// @vitest-environment jsdom

/**
 * The list of Data Canvases: a refused delete says so where it was asked, and the list is only ever this workspace's.
 *
 * 2026-10-13. A delete the server refused closed the confirm and re-read the list as if the canvas were gone — the
 * helper never looked at the answer. And the list was read before the app knew its workspace: read without one, the
 * server answers with every workspace's canvases, and when that answer landed after the scoped one it stayed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasBrowser } from "@/components/CanvasBrowser";
import type { Canvas } from "@/lib/api";
import { fireEvent, render, screen } from "@/lib/testing";

const api = vi.hoisted(() => ({ getCanvases: vi.fn() }));

// Only the read is mocked. The delete is the real helper, so the test holds what it does with a refusal; the one
// request it makes is answered by the stub below, and anything else fails.
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getCanvases: api.getCanvases,
}));

const canvas = (id: string, name: string): Canvas => ({
  id, name, description: "", is_legacy: false, created_at: "", updated_at: "",
  scopes: [{ connection_id: "thelook", schema_name: "thelook", tables: [] }],
});
const RETURNS = canvas("cv1", "Returns");
const ORDERS = canvas("cv2", "Orders");
const REFUNDS = canvas("cv3", "Refunds");

const browser = (workspaceId: string) =>
  <CanvasBrowser connections={[]} workspaceId={workspaceId} onSelect={vi.fn()} onNew={vi.fn()} />;
const settle = () => new Promise(r => setTimeout(r, 10));

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
}

beforeEach(() => { api.getCanvases.mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("deleting a canvas", () => {
  it("says a refused delete was refused, and why, on the confirm — and keeps the canvas", async () => {
    api.getCanvases.mockResolvedValue([RETURNS]);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE" && String(input).endsWith("/canvases/cv1")) {
        return new Response(JSON.stringify({ detail: "Only its owner can delete it" }), { status: 403 });
      }
      throw new Error(`no network — ${String(input)}`);
    }));
    render(browser("ws1"));

    fireEvent.click(await screen.findByTitle("Delete Data Canvas"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Not deleted — Only its owner can delete it");
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();   // the confirm is still open
    expect(screen.getAllByText("Returns").length).toBeGreaterThan(0);              // and the canvas still listed
    expect(api.getCanvases).toHaveBeenCalledTimes(1);                              // not re-read as if it were gone
  });
});

describe("the list is this workspace's", () => {
  it("waits for the workspace before reading the list, then reads that workspace's", async () => {
    api.getCanvases.mockResolvedValue([RETURNS]);
    const { rerender } = render(browser(""));
    await settle();
    expect(api.getCanvases).not.toHaveBeenCalled();     // an unscoped read answers with every workspace's canvases
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("No Data Canvases yet")).toBeNull();

    rerender(browser("ws1"));
    expect(await screen.findByText("Returns")).toBeInTheDocument();
    expect(api.getCanvases.mock.calls).toEqual([["ws1"]]);
  });

  it("a switch never shows the last workspace's canvases, nor an answer that lands after it left", async () => {
    const late = deferred<Canvas[]>();
    api.getCanvases.mockImplementation((ws: string) =>
      ws === "ws1" ? Promise.resolve([RETURNS]) : ws === "ws2" ? late.promise : Promise.resolve([ORDERS]));
    const { rerender } = render(browser("ws1"));
    expect(await screen.findByText("Returns")).toBeInTheDocument();

    rerender(browser("ws2"));                             // its answer is still on the way
    expect(screen.queryByText("Returns")).toBeNull();
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    rerender(browser("ws3"));
    expect(await screen.findByText("Orders")).toBeInTheDocument();
    late.resolve([REFUNDS]);                              // ws2's answer lands after the screen left it
    await settle();
    expect(screen.queryByText("Refunds")).toBeNull();
    expect(screen.getByText("Orders")).toBeInTheDocument();
  });
});
