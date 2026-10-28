// @vitest-environment jsdom

/**
 * The builder's frame (Arc AP-1; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.4 and §4.7): the dashboard between its
 * layout and the setup of what is chosen. What is pinned is what each part hands on — the element chosen, a step of one
 * grade, a change as the next spec — and that a change the rules refuse is said and never handed on. The dashboard itself
 * is a stub here (`ComposedDashboard` is tested on its own); what it is handed is what is asserted.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { useState } from "react";

import { DashboardBuilder, EditBar, MIN_LAYOUT } from "@/components/dashboards/DashboardBuilder";
import { ComposedDashboard, type DashboardHandle } from "@/components/dashboards/ComposedDashboard";
import { regrid } from "@/lib/dashboards/edit";
import type { DashboardSpec } from "@/lib/dashboards/edit";

const toasts = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/components/ui/toast", async (original) => ({ ...(await original<typeof import("@/components/ui/toast")>()), toast: toasts }));
// what the ontology calls each entity, read once a connection — never from a live API in a test
vi.mock("@/lib/objects", async (original) => ({
  ...(await original<typeof import("@/lib/objects")>()),
  cachedObjectCatalog: vi.fn(async () => ({ object_types: [{ object_type: "order", id: "Order", display_name: "Customer Order" }] })),
  // what a set holds now, in the Data tab (Arc AP-2): one count, never the live door
  queryObjects: vi.fn(async (b: { object_type?: string; segment?: string }) => (b.object_type === "nowhere"
    ? { path: "refused", refused: "no entity 'nowhere' here", available: [] }
    : { path: "compiled", rows: [[b.segment ? "1327" : "6619"]], caveats: [], error: null })),
}));
// the setup reads the ontology for a piece over an entity; these tests choose pieces that read none, or wait for none
vi.mock("@/lib/objectTypes", async (original) => ({
  ...(await original<typeof import("@/lib/objectTypes")>()), getObjectType: vi.fn(() => new Promise(() => {})), getProcesses: vi.fn(() => new Promise(() => {})),
}));

function objectDashboard(): DashboardSpec {
  return {
    root: "cockpit",
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Orders" }, children: ["filters", "sec", "sec-2"] },
      filters: { type: "ObjectFilters", props: { entity: "order", properties: [{ path: "status", label: "Status" }] }, children: [] },
      sec: { type: "Section", props: { title: "Orders", grid: 12 }, children: ["chart", "table"] },
      chart: { type: "ObjectChart", props: { entity: "order", label: "Orders per day", time: "created_at", w: 12, h: 6 }, children: [] },
      table: { type: "ObjectTable", props: { entity: "order", w: 8, h: 8 }, children: [] },
      "sec-2": { type: "Section", props: { title: "Notes" }, children: ["note"] },
      note: { type: "Note", props: { text: "Watch the overdue ones", size: "small" }, children: [] },
    },
  };
}

/** The builder around a stub dashboard that hands it `room` and records every step and every element chosen. */
function build(spec: DashboardSpec, room: Record<string, { w: number; h: number }> = {}) {
  const onChange = vi.fn();
  const step = vi.fn();
  const seen: { selected: string | null }[] = [];
  const handle: DashboardHandle = { room: key => room[key] ?? null, step };
  const view = render(
    <DashboardBuilder spec={spec} onChange={onChange} connectionId="thelook" schema="thelook"
      bar={<EditBar picker={<span>Orders</span>} saved="saved 21:42 · version 7" canUndo canRedo={false}
        onUndo={vi.fn()} onRedo={vi.fn()} onDone={vi.fn()} actions={null} />}>
      {({ selected, handle: h }) => {
        h.current = handle;
        seen.push({ selected });
        return <div data-testid="dashboard-stub" data-selected={selected ?? ""} />;
      }}
    </DashboardBuilder>,
  );
  const line = (key: string) => screen.getAllByTestId("builder-line").find(b => b.dataset.key === key)!;
  return { onChange, step, seen, line, view };
}

beforeEach(() => { toasts.error.mockReset(); toasts.success.mockReset(); });

describe("the layout", () => {
  it("is the dashboard as a tree of lines, each named by what it reads, its room beside it", () => {
    const { line } = build(objectDashboard());
    const lines = screen.getAllByTestId("builder-line");
    expect(lines.map(l => l.dataset.key)).toEqual(["cockpit", "filters", "sec", "chart", "table", "sec-2", "note"]);
    expect(line("chart")).toHaveTextContent("Orders per day");
    expect(line("chart")).toHaveTextContent("12 × 6");
    expect(line("table")).toHaveTextContent("order");
    expect(line("note")).toHaveTextContent("Watch the overdue ones");
    expect(screen.getByTestId("setup-empty")).toBeInTheDocument();
  });

  it("names an entity as the ontology names it, once its catalog is read", async () => {
    const { line } = build(objectDashboard());
    await waitFor(() => expect(line("filters")).toHaveTextContent("Customer Order"));
    expect(line("table")).toHaveTextContent("Customer Order");
    expect(line("filters")).not.toHaveTextContent(/^order/);
  });

  it("chooses the element a line names — outlined on the dashboard, marked in the tree, its setup opened", () => {
    const { line, seen } = build(objectDashboard());
    fireEvent.click(line("sec-2"));
    expect(line("sec-2")).toHaveAttribute("aria-selected", "true");
    expect(seen.at(-1)!.selected).toBe("sec-2");
    expect(screen.getByTestId("piece-setup")).toHaveAttribute("data-kind", "Section");
    expect(within(screen.getByTestId("builder-selection")).getByText("Notes")).toBeInTheDocument();
  });
});

describe("the bar above the dashboard", () => {
  it("steps a piece's width and height one grade at a time, and no further than its kind may take", () => {
    const { line, step } = build(objectDashboard(), { chart: { w: 12, h: 6 }, table: { w: 4, h: 20 } });
    fireEvent.click(line("chart"));
    expect(screen.getByTestId("builder-width")).toHaveTextContent("12");
    expect(screen.getByTestId("builder-height")).toHaveTextContent("6");
    expect(screen.getByRole("button", { name: "Width: one grade more" })).toBeDisabled();      // a chart is 12 columns at most
    fireEvent.click(screen.getByRole("button", { name: "Height: one grade more" }));
    fireEvent.click(screen.getByRole("button", { name: "Width: one grade less" }));
    expect(step.mock.calls).toEqual([["chart", 0, 1], ["chart", -1, 0]]);
    fireEvent.click(line("table"));
    expect(screen.getByRole("button", { name: "Width: one grade less" })).toBeDisabled();      // a table is 4 columns at least
    expect(screen.getByRole("button", { name: "Height: one grade more" })).toBeDisabled();     // and 20 rows at most
  });

  it("widens the filter column 40 px at a time, said in pixels", () => {
    const { line, onChange } = build(objectDashboard());
    fireEvent.click(line("filters"));
    expect(screen.getByTestId("builder-width")).toHaveTextContent("7");
    expect(screen.getByTestId("builder-selection")).toHaveTextContent("280 px");
    fireEvent.click(screen.getByRole("button", { name: "Width: one grade more" }));
    const [next, note] = onChange.mock.calls[0];
    expect(next.elements.filters.props.w).toBe(8);
    expect(note).toBe("the filter column resized by hand");
  });

  it("moves an element earlier or later, never before the filter column", () => {
    const { line, onChange } = build(objectDashboard());
    fireEvent.click(line("sec"));
    expect(screen.getByRole("button", { name: "Move earlier" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Move later" }));
    expect(onChange.mock.calls[0][0].elements.cockpit.children).toEqual(["filters", "sec-2", "sec"]);
  });

  it("takes an element off with what it holds, and nothing it held is left behind", () => {
    const { line, onChange } = build(objectDashboard());
    fireEvent.click(line("sec-2"));
    fireEvent.click(screen.getByTestId("builder-take-off"));
    const [next, note] = onChange.mock.calls[0];
    expect(next.elements["sec-2"]).toBeUndefined();
    expect(next.elements.note).toBeUndefined();
    expect(note).toBe("taken off by hand");
  });

  it("says a change the rules refuse, and hands nothing on", () => {
    const lone: DashboardSpec = { root: "c", elements: {
      c: { type: "Cockpit", props: { title: "Lone" }, children: ["s"] },
      s: { type: "Section", props: { title: "Only" }, children: ["n"] },
      n: { type: "Note", props: { text: "the one thing here" }, children: [] },
    } };
    const { line, onChange } = build(lone);
    fireEvent.click(line("s"));
    fireEvent.click(screen.getByTestId("builder-take-off"));
    expect(onChange).not.toHaveBeenCalled();
    expect(toasts.error).toHaveBeenCalledWith("That change is not made", expect.objectContaining({ description: expect.any(String) }));
  });

  it("no longer chooses an element taken off", () => {
    const { line, seen, view } = build(objectDashboard());
    fireEvent.click(line("note"));
    const next = objectDashboard();
    next.elements["sec-2"].children = [];
    delete next.elements.note;
    delete next.elements["sec-2"];
    next.elements.cockpit.children = ["filters", "sec"];
    view.rerender(
      <DashboardBuilder spec={next} onChange={vi.fn()} connectionId="thelook" bar={null}>
        {({ selected }) => { seen.push({ selected }); return <div />; }}
      </DashboardBuilder>,
    );
    expect(seen.at(-1)!.selected).toBeNull();
  });
});

describe("the canvas's room (the study §4.7)", () => {
  let observers: (() => void)[] = [];
  let canvasWidth = 0;
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      cb: () => void;
      constructor(cb: () => void) { this.cb = cb; }
      observe() { observers.push(this.cb); }
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get(this: HTMLElement) { return this.dataset.testid === "builder-canvas" ? canvasWidth : 0; },
    });
  });
  afterEach(() => { observers = []; });

  it("draws the dashboard at 100% where there is room for the page", () => {
    canvasWidth = 1336;                                              // 1920 less the folded rail, the layout and the setup
    build(objectDashboard());
    act(() => observers.forEach(cb => cb()));
    expect(screen.getByTestId("builder-zoom")).toHaveTextContent("100%");
    expect(screen.getByTestId("builder-zoom")).toBeDisabled();
    expect(screen.getByTestId("builder-page").style.width).toBe("1304px");
  });

  it("fits a narrower canvas and says the zoom; 100% on the person's word, and back", () => {
    canvasWidth = 925;                                               // a 14-inch laptop's 1512
    build(objectDashboard());
    act(() => observers.forEach(cb => cb()));
    const zoom = screen.getByTestId("builder-zoom");
    expect(zoom).toHaveTextContent("Fit · 81%");
    const page = screen.getByTestId("builder-page");
    expect(page.style.width).toBe(`${MIN_LAYOUT}px`);
    expect(page.style.transform).toMatch(/^scale\(0\.81/);
    fireEvent.click(zoom);
    expect(zoom).toHaveTextContent("100%");
    expect(page.style.transform).toBe("");
    fireEvent.click(zoom);
    expect(zoom).toHaveTextContent("Fit · 81%");
  });
});

describe("with the dashboard itself drawn", () => {
  /** The builder around the real renderer, its spec kept in state as the page keeps it: each step drawn at once. */
  function Page({ start }: { start: DashboardSpec }) {
    const [spec, setSpec] = useState(start);
    return (
      <DashboardBuilder spec={spec} onChange={next => setSpec(next)} connectionId="thelook" bar={null}>
        {({ selected, onSelect, handle }) => (
          <ComposedDashboard spec={spec} cards={[]} host={{ range: { status: "standing" }, cards: {} }} selected={selected} handle={handle}
            doors={{ onRefresh: vi.fn(), onSelect, onRegrid: (key, box, measured) => setSpec(s => regrid(s, key, box, measured)) }} />
        )}
      </DashboardBuilder>
    );
  }
  const notes: DashboardSpec = { root: "c", elements: {
    c: { type: "Cockpit", props: { title: "Notes" }, children: ["s"] },
    s: { type: "Section", props: { title: "Notes", grid: 12 }, children: ["n"] },
    n: { type: "Note", props: { text: "Watch the overdue ones", w: 6, h: 4 }, children: [] },
  } };

  it("says the room a step has just given, never the one before it", () => {
    globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
    render(<Page start={notes} />);
    fireEvent.click(screen.getAllByTestId("builder-line").find(b => b.dataset.key === "n")!);
    expect(screen.getByTestId("builder-height")).toHaveTextContent("4");
    fireEvent.click(screen.getByRole("button", { name: "Height: one grade more" }));
    expect(document.querySelector('[data-element="n"]')?.getAttribute("data-h")).toBe("5");
    expect(screen.getByTestId("builder-height")).toHaveTextContent("5");
    fireEvent.click(screen.getByRole("button", { name: "Width: one grade less" }));
    expect(screen.getByTestId("builder-width")).toHaveTextContent("5");
  });
});


describe("the Data tab (Arc AP-2)", () => {
  const wired = (): DashboardSpec => ({
    root: "cockpit",
    sets: {
      placed: { label: "Placed", entity: "order" },
      waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
    },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Desk" }, children: ["fig", "table", "note"] },
      fig: { type: "ObjectFigure", props: { set: "waiting", of: "placed", label: "Waiting", agg: "count" }, children: [] },
      table: { type: "ObjectTable", props: { set: "waiting", chooses: "chosen-order" }, children: [] },
      note: { type: "Note", props: { text: "The oldest first" }, children: [] },
    },
  });
  /** The builder, recording what the dashboard is told is dashed. */
  function wire(spec: DashboardSpec) {
    const reads: string[][] = [];
    render(
      <DashboardBuilder spec={spec} onChange={vi.fn()} connectionId="thelook" schema="thelook" bar={null}>
        {({ reads: r }) => { reads.push(r); return <div data-testid="dashboard-stub" />; }}
      </DashboardBuilder>,
    );
    return reads;
  }

  it("lists the sets; choosing one opens its setup and dashes the pieces that read it — and the layout lets it go", async () => {
    const reads = wire(wired());
    fireEvent.click(screen.getByRole("radio", { name: "Variables" }));
    expect(screen.queryByTestId("builder-layout")).toBeNull();
    const sets = within(screen.getByTestId("builder-data")).getAllByTestId("data-set");
    expect(sets.map(s => s.dataset.name)).toEqual(["placed", "waiting"]);
    fireEvent.click(sets[1]);
    expect(screen.getByTestId("set-setup")).toHaveAttribute("data-name", "waiting");
    expect(within(screen.getByTestId("builder-setup")).getByTestId("set-setup")).toBeInTheDocument();
    expect(reads.at(-1)).toEqual(["fig", "table"]);                      // the figure and the list read it; the note does not
    expect(screen.getByTestId("builder-selection")).toHaveTextContent("the 2 pieces that read it are dashed");
    await waitFor(() => expect(sets[1]).toHaveTextContent("1,327"));     // what it holds now, read once
    fireEvent.click(screen.getByRole("radio", { name: "Layout" }));
    expect(reads.at(-1)).toEqual([]);
    expect(screen.getByTestId("builder-layout")).toBeInTheDocument();
    expect(screen.getByTestId("setup-empty")).toBeInTheDocument();
  });
});

describe("building safely (Arc AP-6)", () => {
  it("counts what read cleanly and what is still reading, and lists the ones to fix — each with why, a click choosing it", () => {
    const seen: (string | null)[] = [];
    render(
      <DashboardBuilder spec={objectDashboard()} onChange={vi.fn()} connectionId="thelook" schema="thelook" bar={null}
        checks={{ chart: { status: "ok", reason: "" }, note: { status: "ok", reason: "" }, filters: { status: "reading", reason: "" },
          table: { status: "refused", reason: "This table cannot be read: no property 'promise_date'" }, gone: { status: "refused", reason: "x" } }}>
        {({ selected }) => { seen.push(selected); return <div data-testid="dashboard-stub" />; }}
      </DashboardBuilder>,
    );
    const chip = screen.getByTestId("builder-checks");
    expect(chip).toHaveTextContent("2 read cleanly · 1 reading · 1 to fix");          // an element taken off is not counted
    fireEvent.click(chip);
    const items = screen.getAllByTestId("builder-checks-item");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("no property 'promise_date'");
    fireEvent.click(items[0]);
    expect(seen.at(-1)).toBe("table");
    expect(screen.queryByTestId("builder-checks-list")).toBeNull();
  });

  it("says every piece read cleanly, and offers no list, when none is to fix", () => {
    render(
      <DashboardBuilder spec={objectDashboard()} onChange={vi.fn()} connectionId="thelook" schema="thelook" bar={null}
        checks={{ chart: { status: "ok", reason: "" }, table: { status: "ok", reason: "" } }}>
        {() => <div data-testid="dashboard-stub" />}
      </DashboardBuilder>,
    );
    expect(screen.getByTestId("builder-checks")).toHaveTextContent("2 read cleanly");
    expect(screen.getByTestId("builder-checks")).toBeDisabled();
  });

  it("says how long the door took to count each set", async () => {
    render(
      <DashboardBuilder spec={{ root: "cockpit", sets: { placed: { label: "Placed", entity: "order" } }, elements: {
        cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
        sec: { type: "Section", props: { title: "Desk" }, children: ["fig"] },
        fig: { type: "ObjectFigure", props: { set: "placed", label: "Placed", agg: "count" }, children: [] } } }}
        onChange={vi.fn()} connectionId="thelook" schema="thelook" bar={null}>
        {() => <div data-testid="dashboard-stub" />}
      </DashboardBuilder>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Variables" }));
    await waitFor(() => expect(screen.getByTestId("data-set-read-time")).toHaveTextContent(/^· \d+\.\d{2} s$/));
    fireEvent.click(screen.getByTestId("data-set"));
    await waitFor(() => expect(screen.getByTestId("set-read-time")).toHaveTextContent(/^· counted in \d+\.\d{2} s$/));
  });

  it("says no read time for a set the door could not count", async () => {
    render(
      <DashboardBuilder spec={{ root: "cockpit", sets: { gone: { label: "Gone", entity: "nowhere" } }, elements: {
        cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
        sec: { type: "Section", props: { title: "Desk" }, children: ["fig"] },
        fig: { type: "ObjectFigure", props: { set: "gone", label: "Gone", agg: "count" }, children: [] } } }}
        onChange={vi.fn()} connectionId="thelook" schema="thelook" bar={null}>
        {() => <div data-testid="dashboard-stub" />}
      </DashboardBuilder>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Variables" }));
    await waitFor(() => expect(screen.getByTestId("data-set")).toHaveTextContent("cannot be read"));
    expect(screen.queryByTestId("data-set-read-time")).toBeNull();
    fireEvent.click(screen.getByTestId("data-set"));
    await waitFor(() => expect(screen.getByTestId("set-holds")).toHaveTextContent("cannot be read"));
    expect(screen.queryByTestId("set-read-time")).toBeNull();
  });
});
