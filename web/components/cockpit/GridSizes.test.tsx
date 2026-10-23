// @vitest-environment jsdom

/**
 * Sizes one grade at a time, drawn (Arc AP-1; the user, 2026-10-10: "make sure that these charts tables graphs or
 * filters are size adjustables in a swift manner.. The size needs to be adjusted one grade point at a time"). What is
 * pinned is what the grid is told — jsdom is 0×0, so the section's width is given where a drag needs one — and what
 * each way of resizing hands the cockpit's owner: one grade, held to what the kind may take.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, within } from "@/lib/testing";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { CardState } from "@/components/brief/PinnedCardBody";
import { CanvasScale } from "@/components/cockpit/cellBox";
import { ComposedCockpit, type CockpitDoors, type CockpitHandle } from "@/components/cockpit/ComposedCockpit";
import type { DashboardCard } from "@/lib/api";
import { toGrid, type CockpitSpec } from "@/lib/cockpit/edit";
import type { CockpitHostState } from "@/lib/cockpit/hostState";

vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), graduateCard: vi.fn(), updateDashboardCard: vi.fn() }));
vi.mock("@/components/charts/vega/VegaChart", () => ({ VegaChart: () => <div data-testid="vega" /> }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
  // jsdom has no PointerEvent: a mouse event with a pointer id stands in, so a drag carries its coordinates
  if (!("PointerEvent" in globalThis)) {
    class PointerEventStub extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId ?? 1; }
    }
    (globalThis as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventStub;
  }
});

const premise = (): CockpitSpec => JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

function card(id: string, title: string, value: number): CardState {
  const refresh = { cadence: "daily", last_run: "2026-09-28T06:00:00Z", last_value: value, prev_value: null, history: [value] };
  const c: DashboardCard = {
    id, connection_id: "thelook", scope: "user", scope_ref: "default", source: "authored", kind: "kpi",
    title, sql: "SELECT 1", query_ref: null, render: {}, refresh, thresholds: {},
    provenance: { origin_finding_id: "", receipt_ref: "", metric: "", metric_version: 0 } as DashboardCard["provenance"],
    links: [], body: "", author: "", created_at: "", updated_at: "",
  };
  return { card: c, run: { columns: ["v"], rows: [[value]], row_count: 1, caveats: [], error: null, refresh } };
}

const CARDS = [card("c7f3a001", "Return rate", 0.1003), card("c91b2002", "Net merchandise revenue", 341000)];
const HOST: CockpitHostState = { range: { status: "final" }, cards: { c7f3a001: { status: "within" }, c91b2002: { status: "within" } } };
/** A reader who may not change the cockpit: only a card's refresh. */
const READER: CockpitDoors = { onRefresh: vi.fn() };
const owner = () => {
  const doors = { onRemove: vi.fn(), onRefresh: vi.fn(), onTakeOff: vi.fn(), onResize: vi.fn(), onRegrid: vi.fn() };
  return doors as unknown as CockpitDoors & typeof doors;
};

/** The premise's headline section on the grid, the net revenue card 8 × 6. */
function gridded(): CockpitSpec {
  const s = toGrid(premise(), "sec-headline", { "alert-rate": { w: 3, h: 4 }, "card-rate": { w: 3, h: 4 }, "card-net": { w: 8, h: 6 } });
  return s;
}

const cellOf = (key: string) => document.querySelector(`[data-element="${key}"]`) as HTMLElement;

describe("a section on the grid", () => {
  it("draws twelve columns of one grade, each element across its own columns and rows", () => {
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={READER} />);
    const grid = document.querySelector('[data-grid="12"]') as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe("repeat(12, minmax(0, 1fr))");
    expect(grid.style.gridAutoRows).toBe("28px");
    const net = cellOf("card-net");
    expect(net.dataset).toMatchObject({ w: "8", h: "6" });
    expect(net.style.gridColumn).toBe("span 8");
    expect(net.style.gridRow).toBe("span 6");
  });

  it("offers a reader who may not change it no handle and no key", () => {
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={READER} />);
    expect(screen.queryAllByTestId(/grid-handle/)).toEqual([]);
    expect(cellOf("card-net").tabIndex).toBe(-1);
  });
});

describe("resizing one grade at a time", () => {
  it("Alt and an arrow move an element one column or one row, and no further than its kind allows", () => {
    const doors = owner();
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={doors} />);
    const net = cellOf("card-net");
    fireEvent.keyDown(net, { key: "ArrowRight", altKey: true });
    expect(doors.onRegrid).toHaveBeenLastCalledWith("card-net", { w: 9, h: 6 }, {});
    fireEvent.keyDown(net, { key: "ArrowDown", altKey: true });
    expect(doors.onRegrid).toHaveBeenLastCalledWith("card-net", { w: 8, h: 7 }, {});
    fireEvent.keyDown(net, { key: "ArrowUp", altKey: true });
    expect(doors.onRegrid).toHaveBeenLastCalledWith("card-net", { w: 8, h: 5 }, {});
    // an arrow without Alt is the page's, not a resize
    fireEvent.keyDown(net, { key: "ArrowRight" });
    expect(doors.onRegrid).toHaveBeenCalledTimes(3);
  });

  it("does nothing past a kind's least: a card two rows tall grows no shorter", () => {
    const s = gridded();
    s.elements["card-net"].props.h = 2;
    const doors = owner();
    render(<ComposedCockpit spec={s} cards={CARDS} host={HOST} doors={doors} />);
    fireEvent.keyDown(cellOf("card-net"), { key: "ArrowUp", altKey: true });
    expect(doors.onRegrid).not.toHaveBeenCalled();
  });

  it("on a section sized by name, the first grade moves it onto the grid from the room each element has", () => {
    const doors = owner();
    render(<ComposedCockpit spec={premise()} cards={CARDS} host={HOST} doors={doors} />);
    // jsdom measures nothing, so the room is the one its size by name gives: small is 1 of the section's 3 columns —
    // 4 of 12 — and 4 rows; one grade wider is 5
    fireEvent.keyDown(cellOf("card-rate"), { key: "ArrowRight", altKey: true });
    expect(doors.onRegrid).toHaveBeenCalledWith("card-rate", { w: 5, h: 4 }, {});
  });

  it("a drag of the right edge lands once, on release, as many columns as it crossed — saying the size as it moves", () => {
    const doors = owner();
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={doors} />);
    const grid = document.querySelector('[data-grid="12"]') as HTMLElement;
    // 12 columns of 89 px and 11 gaps of 12: one column and its gap is 101 px
    Object.defineProperty(grid, "clientWidth", { value: 1200, configurable: true });
    const handle = within(cellOf("card-net")).getByTestId("grid-handle-w");
    fireEvent.pointerDown(handle, { clientX: 500, clientY: 300, pointerId: 1 });
    // two columns across — and two grades down, which the right edge does not read: it moves columns only
    fireEvent.pointerMove(handle, { clientX: 500 + 101 * 2 + 20, clientY: 300 + 80 });
    expect(screen.getByTestId("grid-size-said")).toHaveTextContent("10 × 6");
    expect(cellOf("card-net").style.gridColumn).toBe("span 10");
    expect(doors.onRegrid).not.toHaveBeenCalled();
    fireEvent.pointerUp(handle, { clientX: 722, clientY: 300 });
    expect(doors.onRegrid).toHaveBeenCalledTimes(1);
    expect(doors.onRegrid).toHaveBeenCalledWith("card-net", { w: 10, h: 6 }, {});
  });

  it("a drag of the bottom edge moves one row per 40 px, and the corner moves both", () => {
    const doors = owner();
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={doors} />);
    const grid = document.querySelector('[data-grid="12"]') as HTMLElement;
    Object.defineProperty(grid, "clientWidth", { value: 1200, configurable: true });
    const bottom = within(cellOf("card-net")).getByTestId("grid-handle-h");
    fireEvent.pointerDown(bottom, { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(bottom, { clientX: 300, clientY: 3 * 40 + 5 });   // the side-to-side move is not a column here
    fireEvent.pointerUp(bottom, {});
    expect(doors.onRegrid).toHaveBeenLastCalledWith("card-net", { w: 8, h: 9 }, {});
    const corner = within(cellOf("card-net")).getByTestId("grid-handle-both");
    fireEvent.pointerDown(corner, { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(corner, { clientX: -101, clientY: -40 });
    fireEvent.pointerUp(corner, {});
    expect(doors.onRegrid).toHaveBeenLastCalledWith("card-net", { w: 7, h: 5 }, {});
  });

  it("where the grid resizes, the size picked by name is not offered beside it", () => {
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={owner()} />);
    expect(screen.queryAllByTestId("size-pick")).toEqual([]);
    expect(screen.queryAllByTestId("resize-corner")).toEqual([]);
    // every element drawn has its handles (the alert card waits on its condition, and is not drawn)
    const drawn = document.querySelectorAll("[data-element]").length;
    expect(drawn).toBe(2);
    expect(screen.getAllByTestId("grid-handle-both").length).toBe(drawn);
  });
});

describe("the filter column's width", () => {
  const objectCockpit = (w?: number): CockpitSpec => ({
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["filters", "sec"] },
      filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }], ...(w ? { w } : {}) }, children: [] },
      sec: { type: "Section", props: { title: "Orders" }, children: ["card-net"] },
      "card-net": { type: "Card", props: { card: "c91b2002" }, children: [] },
    },
  });

  it("is drawn as it was until a person sets it, then at whole grades of 40 px", () => {
    const { unmount } = render(<ComposedCockpit spec={objectCockpit()} cards={CARDS} host={HOST} doors={READER} />);
    expect(screen.getByTestId("cockpit-filter-column").dataset.width).toBe("272");
    unmount();
    render(<ComposedCockpit spec={objectCockpit(7)} cards={CARDS} host={HOST} doors={READER} />);
    expect(screen.getByTestId("cockpit-filter-column").dataset.width).toBe("280");
  });

  it("is dragged 40 px at a time, held between 200 and 400", () => {
    const onFilterWidth = vi.fn();
    render(<ComposedCockpit spec={objectCockpit(7)} cards={CARDS} host={HOST} doors={{ ...READER, onFilterWidth }} />);
    const handle = screen.getByTestId("filter-width-handle");
    fireEvent.pointerDown(handle, { clientX: 280, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 280 + 85, clientY: 0 });
    expect(screen.getByTestId("filter-width-said")).toHaveTextContent("360 px");
    fireEvent.pointerMove(handle, { clientX: 280 + 900, clientY: 0 });
    expect(screen.getByTestId("filter-width-said")).toHaveTextContent("400 px");
    fireEvent.pointerUp(handle, {});
    expect(onFilterWidth).toHaveBeenCalledWith(10);
  });
});

describe("in the builder (Arc AP-1)", () => {
  it("a piece pointed at is the one chosen, and a click in a section's gap chooses the section", () => {
    const onSelect = vi.fn();
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={{ ...owner(), onSelect }} />);
    fireEvent.pointerDown(cellOf("card-net"));
    expect(onSelect).toHaveBeenLastCalledWith("card-net");
    fireEvent.pointerDown(document.querySelector('[data-testid="cockpit-section"]') as HTMLElement);
    expect(onSelect).toHaveBeenLastCalledWith("sec-headline");
  });

  it("outlines the element chosen, and no other", () => {
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={owner()} selected="card-net" />);
    expect(cellOf("card-net").dataset.selected).toBe("true");
    expect(cellOf("card-net").style.outline).toContain("var(--accent)");
    expect(cellOf("card-rate").dataset.selected).toBeUndefined();
  });

  it("hands the builder each element's room and its steps — one grade, within its kind's limits", () => {
    const doors = owner();
    const handle: { current: CockpitHandle | null } = { current: null };
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={doors} handle={handle} />);
    expect(handle.current?.room("card-net")).toEqual({ w: 8, h: 6 });
    handle.current?.step("card-net", 0, 1);
    expect(doors.onRegrid).toHaveBeenLastCalledWith("card-net", { w: 8, h: 7 }, {});
    expect(handle.current?.room("nothing")).toBeNull();
  });

  it("counts a drag's grades at the dashboard's own size where the canvas draws it scaled", () => {
    const doors = owner();
    render(
      <CanvasScale.Provider value={0.5}>
        <ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={doors} />
      </CanvasScale.Provider>,
    );
    const grid = document.querySelector('[data-grid="12"]') as HTMLElement;
    Object.defineProperty(grid, "clientWidth", { value: 1200, configurable: true });
    const handle = within(cellOf("card-net")).getByTestId("grid-handle-w");
    // 101 px on screen at half size is 202 px of the cockpit's own: two columns, not one
    fireEvent.pointerDown(handle, { clientX: 500, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 601, clientY: 0 });
    fireEvent.pointerUp(handle, {});
    expect(doors.onRegrid).toHaveBeenLastCalledWith("card-net", { w: 10, h: 6 }, {});
  });

  it("a section already on the grid offers no size by name beside it, even where the grid is not offered", () => {
    const doors = { onRefresh: vi.fn(), onResize: vi.fn() };
    render(<ComposedCockpit spec={gridded()} cards={CARDS} host={HOST} doors={doors} />);
    expect(screen.queryAllByTestId("resize-corner")).toEqual([]);
  });
});
