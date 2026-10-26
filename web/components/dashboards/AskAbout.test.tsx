// @vitest-environment jsdom

/**
 * Arc FA-2 — a choice can leave its piece. With `canvas.ask_about_chosen` on, a table with rows ticked offers "Ask about
 * these", and a table reading a named set "Ask about this set"; a click keeps the subject in memory and asks the shell
 * for the Data Canvas with the connection only — no key in the address. Off, the table draws what it drew. Every read is
 * mocked: no test here reaches an API.
 */
import { fireEvent, render, screen, waitFor } from "@/lib/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectListPiece } from "@/components/dashboards/AppPieces";
import { ObjectTablePiece, PiecesProvider } from "@/components/dashboards/OntologyPieces";
import { askSubject, setAskSubject } from "@/lib/askSubject";
import type { DashboardSetDef, DashboardValueDef } from "@/lib/dashboards/catalog";
import { forgetFlags } from "@/lib/flagOn";
import { NAVIGATE_EVENT, type NavigateRequest } from "@/lib/navigate";

const objects = vi.hoisted(() => ({ listObjects: vi.fn(), queryObjects: vi.fn() }));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
const api = vi.hoisted(() => ({ getSystemFlags: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const SETS: Record<string, DashboardSetDef> = {
  waiting: { label: "Late dispatch", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
};
const VALUES: Record<string, DashboardValueDef> = { window: { label: "Window", kind: "days", value: 14 } };
const ELEMENTS = {
  table: { type: "ObjectTable", props: { set: "waiting", ticks: "ticked-orders", columns: ["status"] } },
  every: { type: "ObjectTable", props: { entity: "order", ticks: "ticked-all", columns: ["status"] } },
  list: { type: "ObjectList", props: { set: "waiting", ticks: "ticked-list", title: "status" } },
};
const page = () => ({
  path: "listed", object_type: "order", type_id: "Order", key: "id", title: "", segment_said: "",
  columns: [{ name: "status", path: "status", label: "status", type: "VARCHAR", edited: false }],
  names: ["id", "status"], rows: [["38330", "Processing"], ["79251", "Processing"]],
  total: 1400, offset: 0, limit: 6, plan: [], caveats: [], error: null,
});

let went: NavigateRequest[] = [];
const onNavigate = (e: Event) => went.push((e as CustomEvent<NavigateRequest>).detail);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  forgetFlags();
  setAskSubject(null);
  went = [];
  window.addEventListener(NAVIGATE_EVENT, onNavigate);
  objects.listObjects.mockImplementation(async () => page());
  api.getSystemFlags.mockResolvedValue({ "canvas.ask_about_chosen": { value: true } });
});
afterEach(() => window.removeEventListener(NAVIGATE_EVENT, onNavigate));

function draw(piece: "table" | "every" | "list" = "table") {
  return render(
    <PiecesProvider connectionId="thelook" elements={ELEMENTS} sets={SETS} values={VALUES} dashboardId="thelook:desk-3f2a1c">
      {piece === "list"
        ? <ObjectListPiece elementKey="list" set="waiting" ticks="ticked-list" title="status" />
        : piece === "every"
          ? <ObjectTablePiece elementKey="every" entity="order" ticks="ticked-all" columns={["status"]} tall={false} />
          : <ObjectTablePiece elementKey="table" set="waiting" ticks="ticked-orders" columns={["status"]} tall={false} />}
    </PiecesProvider>);
}

describe("asking about what a reader chose", () => {
  it("offers the set a table reads, and carries it by name with the page's values — the address holds the connection only", async () => {
    draw();
    fireEvent.click(await screen.findByTestId("ask-about-set"));
    expect(askSubject()).toEqual({ kind: "set", connectionId: "thelook", noun: ["order", "orders"], dashboard: "desk-3f2a1c",
      set: "waiting", label: "Late dispatch", total: 1400, values: { window: 14 }, chosen: {}, filters: [], narrowed: false });
    expect(went).toEqual([{ tab: "chat", params: { conn: "thelook" } }]);
  });

  it("offers the objects ticked instead, by reference, once a row is ticked", async () => {
    draw();
    await screen.findByTestId("ask-about-set");
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 38330" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 79251" }));
    expect(screen.queryByTestId("ask-about-set")).toBeNull();
    fireEvent.click(screen.getByTestId("ask-about-ticked"));
    expect(askSubject()).toEqual({ kind: "objects", connectionId: "thelook", noun: ["order", "orders"],
      refs: ["order:38330", "order:79251"], label: "Late dispatch" });
    expect(went).toEqual([{ tab: "chat", params: { conn: "thelook" } }]);
  });

  it("offers ticked objects from a list of cards too", async () => {
    draw("list");
    await screen.findByTestId("ask-about-set");
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 38330" }));
    fireEvent.click(screen.getByTestId("ask-about-ticked"));
    expect(askSubject()).toMatchObject({ kind: "objects", refs: ["order:38330"] });
  });

  it("names no set for a table over every object of an entity, and still offers what is ticked", async () => {
    draw("every");
    await waitFor(() => expect(screen.getAllByTestId("object-table-row")).toHaveLength(2));
    expect(screen.queryByTestId("ask-about-set")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 38330" }));
    expect(screen.getByTestId("ask-about-ticked")).toBeInTheDocument();
  });

  it("is not offered while the flag is off, and the table draws what it drew", async () => {
    api.getSystemFlags.mockResolvedValue({ "canvas.ask_about_chosen": { value: false } });
    draw();
    await waitFor(() => expect(screen.getAllByTestId("object-table-row")).toHaveLength(2));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tick 38330" }));
    expect(screen.queryByTestId("ask-about-ticked")).toBeNull();
    expect(screen.queryByTestId("ask-about-set")).toBeNull();
    expect(api.getSystemFlags).toHaveBeenCalled();
  });
});
